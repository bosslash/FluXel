use std::{collections::BTreeMap, fs, path::Path};

use anyhow::{Context, Result, bail};
use chrono::{Duration, Local, NaiveDate};
use regex::Regex;
use rusqlite::{Connection, OptionalExtension, params};
use uuid::Uuid;

mod gantt;
mod quick_access;
mod tasks;

pub use quick_access::split_tags;
pub use tasks::{normalize_description, strip_storage_markers};

use crate::{
    models::{
        DashboardSnapshot, GanttProject, GanttTerm, QuickAccessItem, QuickAccessKind, Task,
        normalized_importance,
    },
    paths::AppPaths,
};

#[derive(Clone, Debug)]
pub struct Storage {
    pub paths: AppPaths,
}

impl Storage {
    pub fn new(paths: AppPaths) -> Result<Self> {
        fs::create_dir_all(&paths.state_dir)
            .with_context(|| format!("failed to create {}", paths.state_dir.display()))?;
        fs::create_dir_all(&paths.database_dir)
            .with_context(|| format!("failed to create {}", paths.database_dir.display()))?;
        if let Some(parent) = paths.settings_file.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("failed to create {}", parent.display()))?;
        }
        let storage = Self { paths };
        storage.ensure_all()?;
        Ok(storage)
    }

    pub fn ensure_all(&self) -> Result<()> {
        self.ensure_tasks()?;
        self.ensure_quick_access()?;
        self.ensure_gantt()?;
        Ok(())
    }

    pub fn export_tasks_db(&self, destination: &Path) -> Result<()> {
        if destination == self.paths.tasks_db() {
            bail!("export destination must be different from Tasks.db");
        }
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("failed to create {}", parent.display()))?;
        }
        let source = Self::connect(&self.paths.tasks_db())?;
        source
            .backup("main", destination, None)
            .with_context(|| format!("failed to export {}", destination.display()))
    }

    pub fn export_settings(&self, destination: &Path) -> Result<()> {
        if destination == self.paths.settings_file {
            bail!("export destination must be different from settings.ini");
        }
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("failed to create {}", parent.display()))?;
        }
        fs::copy(&self.paths.settings_file, destination)
            .with_context(|| format!("failed to export {}", destination.display()))?;
        Ok(())
    }

    fn connect(path: &Path) -> Result<Connection> {
        let conn =
            Connection::open(path).with_context(|| format!("failed to open {}", path.display()))?;
        conn.execute_batch("PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000;")?;
        Ok(conn)
    }
}

/// Adds a legacy-compatible column only when an older database does not have it.
fn ensure_column(conn: &Connection, table: &str, column: &str, definition: &str) -> Result<()> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info({table})"))?;
    let names = stmt
        .query_map([], |row| row.get::<_, String>(1))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if !names.iter().any(|name| name == column) {
        conn.execute(
            &format!("ALTER TABLE {table} ADD COLUMN {column} {definition}"),
            [],
        )?;
    }
    Ok(())
}

/// Uses the timestamp format already stored by the Python application.
fn now_string() -> String {
    Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()
}

#[cfg(test)]
mod tests;
