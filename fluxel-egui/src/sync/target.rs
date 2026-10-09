//! Append-only folder transport compatible with `.fluxel-sync/v1`.

use std::{
    collections::{HashMap, HashSet},
    fs,
    io::Write,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result, bail};
use chrono::{Datelike, SecondsFormat, Utc};
use serde_json::{Map, Value, json};
use uuid::Uuid;

use super::types::{FORMAT_VERSION, SUPPORTED_KINDS, SyncEvent, content_hash};

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct TargetSummary {
    pub initialized: bool,
    pub event_count: usize,
    pub active_item_count: usize,
    pub device_count: usize,
}

pub struct FolderTarget {
    pub root: PathBuf,
}

impl FolderTarget {
    pub fn new(selected_folder: &Path) -> Self {
        Self {
            root: selected_folder.join(".fluxel-sync").join("v1"),
        }
    }

    pub fn initialize(&self) -> Result<()> {
        fs::create_dir_all(self.root.join("events"))?;
        let info = self.root.join("info.json");
        if !info.exists() {
            atomic_json_write(
                &info,
                &json!({
                    "format": "Fluxel folder sync",
                    "format_version": FORMAT_VERSION,
                    "created_at": utc_now(),
                }),
            )?;
        }
        self.validate_info()
    }

    pub fn events(&self) -> Result<Vec<SyncEvent>> {
        let mut paths = Vec::new();
        collect_json_files(&self.root.join("events"), &mut paths)?;
        paths.sort();
        paths
            .into_iter()
            .map(|path| self.read_event(&path))
            .collect()
    }

    pub fn read_event(&self, path: &Path) -> Result<SyncEvent> {
        let text = fs::read_to_string(path)
            .with_context(|| format!("cannot read sync event {}", path.display()))?;
        let event: SyncEvent = serde_json::from_str(&text)
            .with_context(|| format!("invalid sync event {}", path.display()))?;
        if event.format_version != FORMAT_VERSION {
            bail!("unsupported sync event version: {}", path.display());
        }
        if !SUPPORTED_KINDS.contains(&event.kind.as_str()) {
            bail!("unsupported sync item type: {}", event.kind);
        }
        if event.item_hash != content_hash(event.data.as_ref()) {
            bail!("sync event checksum mismatch: {}", path.display());
        }
        Ok(event)
    }

    pub fn write_event(
        &self,
        device_id: &str,
        kind: &str,
        entity_id: &str,
        operation: &str,
        base_hash: Option<String>,
        data: Option<Map<String, Value>>,
    ) -> Result<SyncEvent> {
        self.initialize()?;
        let now = Utc::now();
        let event = SyncEvent {
            format_version: FORMAT_VERSION,
            event_id: Uuid::now_v7().to_string(),
            device_id: device_id.to_owned(),
            kind: kind.to_owned(),
            entity_id: entity_id.to_owned(),
            operation: operation.to_owned(),
            created_at: now.to_rfc3339_opts(SecondsFormat::Millis, true),
            base_hash,
            item_hash: content_hash(data.as_ref()),
            data,
        };
        let filename = format!("{}_{}.json", event.event_id, safe_component(device_id));
        let path = self
            .root
            .join("events")
            .join(kind)
            .join(format!("{:04}", now.year()))
            .join(format!("{:02}", now.month()))
            .join(filename);
        atomic_json_write(&path, &serde_json::to_value(&event)?)?;
        Ok(event)
    }

    pub fn summary(&self) -> Result<TargetSummary> {
        let initialized = self.root.join("info.json").is_file();
        if !initialized {
            return Ok(TargetSummary::default());
        }
        self.validate_info()?;
        let events = self.events()?;
        let mut latest = HashMap::new();
        let mut devices = HashSet::new();
        for event in &events {
            devices.insert(event.device_id.clone());
            latest.insert(event.key(), event);
        }
        Ok(TargetSummary {
            initialized,
            event_count: events.len(),
            active_item_count: latest
                .values()
                .filter(|event| event.operation != "delete")
                .count(),
            device_count: devices.len(),
        })
    }

    fn validate_info(&self) -> Result<()> {
        let value: Value = serde_json::from_str(&fs::read_to_string(self.root.join("info.json"))?)?;
        if value.get("format_version").and_then(Value::as_u64) != Some(FORMAT_VERSION.into()) {
            bail!("unsupported Fluxel sync target version");
        }
        Ok(())
    }
}

pub fn utc_now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn collect_json_files(root: &Path, output: &mut Vec<PathBuf>) -> Result<()> {
    if !root.is_dir() {
        return Ok(());
    }
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        if path.is_dir() {
            collect_json_files(&path, output)?;
        } else if path
            .extension()
            .is_some_and(|extension| extension == "json")
        {
            output.push(path);
        }
    }
    Ok(())
}

fn safe_component(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_alphanumeric() || matches!(character, '-' | '_') {
                character
            } else {
                '-'
            }
        })
        .take(80)
        .collect()
}

fn atomic_json_write(path: &Path, value: &Value) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let temporary = path.with_file_name(format!(
        "{}.{}.partial",
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("sync"),
        Uuid::new_v4()
    ));
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)?;
    file.write_all(serde_json::to_string(value)?.as_bytes())?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    fs::rename(&temporary, path)?;
    Ok(())
}
