use std::{
    env, fs,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result};

#[derive(Clone, Debug)]
pub struct AppPaths {
    pub state_dir: PathBuf,
    pub database_dir: PathBuf,
    pub settings_file: PathBuf,
}

impl AppPaths {
    pub fn discover() -> Result<Self> {
        if let Some(raw) = env::var_os("FLUXEL_DATA_DIR") {
            let root = PathBuf::from(raw);
            fs::create_dir_all(&root)
                .with_context(|| format!("failed to create {}", root.display()))?;
            return Ok(Self {
                state_dir: root.clone(),
                database_dir: root.clone(),
                settings_file: root.join("settings.ini"),
            });
        }

        let state_dir = platform_state_dir()?;
        fs::create_dir_all(&state_dir)
            .with_context(|| format!("failed to create {}", state_dir.display()))?;

        let locator = state_dir.join("location.ini");
        let entries = parse_storage_locator(&locator);
        let database_dir = entries
            .iter()
            .find(|(key, _)| key == "database_dir")
            .map(|(_, value)| expand_path(value))
            .filter(|path| path.is_absolute())
            .unwrap_or_else(|| state_dir.clone());
        let settings_file = entries
            .iter()
            .find(|(key, _)| key == "settings_file")
            .map(|(_, value)| expand_path(value))
            .filter(|path| path.is_absolute())
            .unwrap_or_else(|| state_dir.join("settings.ini"));
        fs::create_dir_all(&database_dir)
            .with_context(|| format!("failed to create {}", database_dir.display()))?;

        Ok(Self {
            state_dir,
            database_dir,
            settings_file,
        })
    }

    pub fn tasks_db(&self) -> PathBuf {
        self.database_dir.join("Tasks.db")
    }

    pub fn quick_access_db(&self) -> PathBuf {
        self.database_dir.join("QuickAccess.db")
    }

    pub fn planning_db(&self) -> PathBuf {
        self.database_dir.join("Planning.db")
    }
}

fn platform_state_dir() -> Result<PathBuf> {
    #[cfg(target_os = "windows")]
    {
        let local = env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .context("LOCALAPPDATA is not set")?;
        return Ok(local.join("Fluxel"));
    }

    #[cfg(not(target_os = "windows"))]
    {
        let home = dirs::home_dir().context("home directory is unavailable")?;
        // Prefer the existing PySide location so both versions can share data.
        let legacy = home.join("AppData").join("Local").join("Fluxel");
        if legacy.exists() {
            return Ok(legacy);
        }
        let base = dirs::data_local_dir().unwrap_or_else(|| home.join(".local/share"));
        Ok(base.join("Fluxel"))
    }
}

fn parse_storage_locator(path: &Path) -> Vec<(String, String)> {
    let Ok(text) = fs::read_to_string(path) else {
        return Vec::new();
    };
    let mut in_storage = false;
    text.lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.starts_with('[') && line.ends_with(']') {
                in_storage = line.eq_ignore_ascii_case("[storage]");
                return None;
            }
            if !in_storage || line.is_empty() || line.starts_with(['#', ';']) {
                return None;
            }
            let (key, value) = line.split_once('=')?;
            Some((key.trim().to_lowercase(), value.trim().to_owned()))
        })
        .collect()
}

fn expand_path(raw: &str) -> PathBuf {
    if let Some(rest) = raw.strip_prefix("~/")
        && let Some(home) = dirs::home_dir()
    {
        return home.join(rest);
    }
    let mut value = raw.to_owned();
    for (key, replacement) in env::vars() {
        value = value.replace(&format!("%{key}%"), &replacement);
        value = value.replace(&format!("${{{key}}}"), &replacement);
    }
    PathBuf::from(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_only_storage_section() {
        let temp = tempfile::tempdir().unwrap();
        let locator = temp.path().join("location.ini");
        std::fs::write(
            &locator,
            "[other]\ndatabase_dir=/bad\n[storage]\ndatabase_dir = /data\nsettings_file=/cfg/settings.ini\n",
        )
        .unwrap();
        let values = parse_storage_locator(&locator);
        assert_eq!(values.len(), 2);
        assert_eq!(values[0], ("database_dir".to_owned(), "/data".to_owned()));
    }
}
