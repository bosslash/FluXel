//! OneDrive-folder synchronization compatible with the Python implementation.
//!
//! Every device keeps local SQLite databases. Changes are exchanged as
//! append-only, checksummed JSON events under `.fluxel-sync/v1`, so neither
//! client opens a database file inside a cloud-synchronized directory.

mod repository;
mod state;
mod target;
mod types;

use std::{path::Path, sync::Mutex};

use anyhow::{Result, bail};

use crate::storage::Storage;

use repository::LocalRepository;
use state::SyncState;
use target::FolderTarget;
pub use target::TargetSummary;
use types::SyncItem;
pub use types::SyncReport;

static SYNC_LOCK: Mutex<()> = Mutex::new(());

/// Reads sync-folder metadata without modifying local or remote state.
pub fn inspect(folder: &Path) -> Result<TargetSummary> {
    FolderTarget::new(folder).summary()
}

/// Merges remote events, records conflicts, then uploads local changes.
pub fn synchronize(storage: &Storage, folder: &Path) -> Result<SyncReport> {
    let Ok(_guard) = SYNC_LOCK.try_lock() else {
        bail!("a synchronization is already running");
    };
    let target = FolderTarget::new(folder);
    target.initialize()?;
    let state = SyncState::open(&storage.paths.state_dir.join("SyncState.db"))?;
    state.bind_target(&target.root.display().to_string())?;
    let device_id = state.device_id()?;
    let repository = LocalRepository::new(storage);
    let mut report = SyncReport::default();

    let mut current = repository.collect_items()?;
    let mut records = state.records()?;
    let mut events = target.events()?;
    events.sort_by(|left, right| {
        (&left.created_at, &left.event_id).cmp(&(&right.created_at, &right.event_id))
    });
    let mut applied = state.applied_ids()?;

    for event in events {
        if applied.contains(&event.event_id) {
            continue;
        }
        let key = event.key();
        let local = current.get(&key);
        let local_hash = local.map(SyncItem::hash);
        let baseline_hash = records
            .get(&key)
            .and_then(|record| record.content_hash.clone());
        let local_dirty = local_hash != baseline_hash;
        let remote_matches_local = event.item_hash == local_hash;

        if local_dirty && !remote_matches_local {
            state.add_conflict(
                &key,
                &event.event_id,
                local.map(|item| &item.data),
                event.data.as_ref(),
            )?;
            report.conflicts += 1;
            state.set_record(
                &key,
                &event.kind,
                &event.entity_id,
                event.item_hash.as_deref(),
                event.data.as_ref(),
            )?;
        } else if remote_matches_local {
            state.set_record(
                &key,
                &event.kind,
                &event.entity_id,
                event.item_hash.as_deref(),
                event.data.as_ref(),
            )?;
        } else {
            repository.apply_event(&event)?;
            if event.operation == "delete" {
                current.remove(&key);
                report.deleted += 1;
            } else if let Some(data) = event.data.clone() {
                current.insert(
                    key.clone(),
                    SyncItem {
                        kind: event.kind.clone(),
                        entity_id: event.entity_id.clone(),
                        data,
                    },
                );
                report.downloaded += 1;
            }
            state.set_record(
                &key,
                &event.kind,
                &event.entity_id,
                event.item_hash.as_deref(),
                event.data.as_ref(),
            )?;
        }
        state.mark_applied(&event.event_id)?;
        applied.insert(event.event_id);
        records = state.records()?;
    }

    current = repository.collect_items()?;
    records = state.records()?;
    let mut keys = current.keys().cloned().collect::<Vec<_>>();
    keys.sort();
    for key in keys {
        let item = &current[&key];
        let baseline = records
            .get(&key)
            .and_then(|record| record.content_hash.clone());
        if Some(item.hash()) == baseline {
            continue;
        }
        let event = target.write_event(
            &device_id,
            &item.kind,
            &item.entity_id,
            "upsert",
            baseline,
            Some(item.data.clone()),
        )?;
        state.set_record(
            &key,
            &item.kind,
            &item.entity_id,
            event.item_hash.as_deref(),
            Some(&item.data),
        )?;
        state.mark_applied(&event.event_id)?;
        report.uploaded += 1;
    }

    let mut deleted_keys = state.records()?.into_iter().collect::<Vec<_>>();
    deleted_keys.sort_by(|left, right| left.0.cmp(&right.0));
    for (key, record) in deleted_keys {
        if current.contains_key(&key) || record.content_hash.is_none() {
            continue;
        }
        let event = target.write_event(
            &device_id,
            &record.kind,
            &record.entity_id,
            "delete",
            record.content_hash,
            None,
        )?;
        state.set_record(&key, &record.kind, &record.entity_id, None, None)?;
        state.mark_applied(&event.event_id)?;
        report.uploaded += 1;
        report.deleted += 1;
    }
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::paths::AppPaths;
    use crate::{models::Task, storage::Storage};

    fn storage_at(path: &Path) -> Storage {
        Storage::new(AppPaths {
            state_dir: path.to_owned(),
            database_dir: path.to_owned(),
            settings_file: path.join("settings.ini"),
        })
        .unwrap()
    }

    #[test]
    fn two_devices_exchange_python_compatible_events() {
        let temp = tempfile::tempdir().unwrap();
        let first = storage_at(&temp.path().join("first"));
        let second = storage_at(&temp.path().join("second"));
        let folder = temp.path().join("OneDrive").join("Fluxel Sync");
        let mut task = Task {
            name: "shared".to_owned(),
            status: "todo".to_owned(),
            ..Task::default()
        };
        first.save_task(&mut task).unwrap();

        let upload = synchronize(&first, &folder).unwrap();
        assert_eq!(upload.uploaded, 1);
        let download = synchronize(&second, &folder).unwrap();
        assert_eq!(download.downloaded, 1);
        assert_eq!(second.get_task(&task.id).unwrap().unwrap().name, "shared");
        assert_eq!(inspect(&folder).unwrap().active_item_count, 1);
    }

    #[test]
    fn canonical_hash_matches_python_json_encoding() {
        let data = serde_json::from_value::<serde_json::Map<String, serde_json::Value>>(
            serde_json::json!({"b": "日本語", "a": 1}),
        )
        .unwrap();
        assert_eq!(
            types::content_hash(Some(&data)).unwrap(),
            "08dd526e9a85dca3ad495c77919e506717f76b036c0952b68d391e42c30ba05b"
        );
    }
}
