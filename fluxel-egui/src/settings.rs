use std::{fs, path::Path};

use anyhow::{Context, Result};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppSettings {
    pub archive_after_days: u32,
    pub export_ini_path: String,
    pub export_sql_path: String,
    pub sync_folder: String,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            archive_after_days: 7,
            export_ini_path: String::new(),
            export_sql_path: String::new(),
            sync_folder: String::new(),
        }
    }
}

impl AppSettings {
    pub fn load(path: &Path) -> Self {
        let Ok(text) = fs::read_to_string(path) else {
            return Self::default();
        };
        let mut result = Self::default();
        let mut section = String::new();
        for raw in text.lines() {
            let line = raw.trim();
            if line.starts_with('[') && line.ends_with(']') {
                section = line[1..line.len() - 1].trim().to_lowercase();
                continue;
            }
            let Some((key, value)) = line.split_once('=') else {
                continue;
            };
            let key = key.trim().to_lowercase();
            let value = value.trim();
            match (section.as_str(), key.as_str()) {
                ("kanban", "archive_after_days") => {
                    result.archive_after_days = value.parse::<u32>().unwrap_or(7).clamp(1, 365);
                }
                ("export", "ini_path") => result.export_ini_path = value.to_owned(),
                ("export", "sql_path") => result.export_sql_path = value.to_owned(),
                ("sync", "folder") => result.sync_folder = value.to_owned(),
                _ => {}
            }
        }
        result
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("failed to create {}", parent.display()))?;
        }
        let text = format!(
            "[kanban]\narchive_after_days = {}\n\n[export]\nini_path = {}\nsql_path = {}\n\n[sync]\nfolder = {}\n",
            self.archive_after_days.clamp(1, 365),
            self.export_ini_path,
            self.export_sql_path,
            self.sync_folder,
        );
        fs::write(path, text).with_context(|| format!("failed to write {}", path.display()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_and_writes_python_compatible_ini() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("settings.ini");
        let expected = AppSettings {
            archive_after_days: 21,
            export_ini_path: "a.ini".to_owned(),
            export_sql_path: "b.db".to_owned(),
            sync_folder: "sync".to_owned(),
        };
        expected.save(&path).unwrap();
        assert_eq!(AppSettings::load(&path), expected);
    }
}
