//! Device-local sync cursors and conflict history.

use std::{collections::HashMap, path::Path};

use anyhow::Result;
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Map, Value};
use uuid::Uuid;

use super::target::utc_now;

#[derive(Clone, Debug)]
pub struct SyncRecord {
    pub kind: String,
    pub entity_id: String,
    pub content_hash: Option<String>,
}

pub struct SyncState {
    connection: Connection,
}

impl SyncState {
    pub fn open(path: &Path) -> Result<Self> {
        let connection = Connection::open(path)?;
        connection.execute_batch(
            "CREATE TABLE IF NOT EXISTS sync_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS sync_records(
                item_key TEXT PRIMARY KEY,kind TEXT NOT NULL,entity_id TEXT NOT NULL,
                content_hash TEXT,payload TEXT,updated_at TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS applied_events(
                event_id TEXT PRIMARY KEY,applied_at TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS sync_conflicts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,item_key TEXT NOT NULL,
                event_id TEXT NOT NULL UNIQUE,local_payload TEXT,remote_payload TEXT,
                detected_at TEXT NOT NULL,resolved_at TEXT);",
        )?;
        Ok(Self { connection })
    }

    pub fn device_id(&self) -> Result<String> {
        if let Some(value) = self
            .connection
            .query_row(
                "SELECT value FROM sync_metadata WHERE key='device_id'",
                [],
                |row| row.get(0),
            )
            .optional()?
        {
            return Ok(value);
        }
        let value = Uuid::new_v4().to_string();
        self.connection.execute(
            "INSERT INTO sync_metadata(key,value) VALUES ('device_id',?1)",
            [&value],
        )?;
        Ok(value)
    }

    pub fn bind_target(&self, target: &str) -> Result<()> {
        let normalized = target.to_lowercase();
        let current: Option<String> = self
            .connection
            .query_row(
                "SELECT value FROM sync_metadata WHERE key='target_key'",
                [],
                |row| row.get(0),
            )
            .optional()?;
        if current.as_deref() == Some(&normalized) {
            return Ok(());
        }
        self.connection.execute_batch(
            "DELETE FROM sync_records; DELETE FROM applied_events; DELETE FROM sync_conflicts;",
        )?;
        self.connection.execute(
            "INSERT INTO sync_metadata(key,value) VALUES ('target_key',?1)
             ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [&normalized],
        )?;
        Ok(())
    }

    pub fn records(&self) -> Result<HashMap<String, SyncRecord>> {
        let mut statement = self
            .connection
            .prepare("SELECT item_key,kind,entity_id,content_hash,payload FROM sync_records")?;
        let rows = statement.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                SyncRecord {
                    kind: row.get(1)?,
                    entity_id: row.get(2)?,
                    content_hash: row.get(3)?,
                },
            ))
        })?;
        Ok(rows.collect::<rusqlite::Result<HashMap<_, _>>>()?)
    }

    pub fn set_record(
        &self,
        key: &str,
        kind: &str,
        entity_id: &str,
        hash: Option<&str>,
        payload: Option<&Map<String, Value>>,
    ) -> Result<()> {
        let payload = payload.map(serde_json::to_string).transpose()?;
        self.connection.execute(
            "INSERT INTO sync_records(item_key,kind,entity_id,content_hash,payload,updated_at)
             VALUES (?1,?2,?3,?4,?5,?6)
             ON CONFLICT(item_key) DO UPDATE SET kind=excluded.kind,
             entity_id=excluded.entity_id,content_hash=excluded.content_hash,
             payload=excluded.payload,updated_at=excluded.updated_at",
            params![key, kind, entity_id, hash, payload, utc_now()],
        )?;
        Ok(())
    }

    pub fn applied_ids(&self) -> Result<std::collections::HashSet<String>> {
        let mut statement = self
            .connection
            .prepare("SELECT event_id FROM applied_events")?;
        Ok(statement
            .query_map([], |row| row.get(0))?
            .collect::<rusqlite::Result<_>>()?)
    }

    pub fn mark_applied(&self, event_id: &str) -> Result<()> {
        self.connection.execute(
            "INSERT OR IGNORE INTO applied_events(event_id,applied_at) VALUES (?1,?2)",
            params![event_id, utc_now()],
        )?;
        Ok(())
    }

    pub fn add_conflict(
        &self,
        key: &str,
        event_id: &str,
        local: Option<&Map<String, Value>>,
        remote: Option<&Map<String, Value>>,
    ) -> Result<()> {
        self.connection.execute(
            "INSERT OR IGNORE INTO sync_conflicts(
                item_key,event_id,local_payload,remote_payload,detected_at)
             VALUES (?1,?2,?3,?4,?5)",
            params![
                key,
                event_id,
                local.map(serde_json::to_string).transpose()?,
                remote.map(serde_json::to_string).transpose()?,
                utc_now()
            ],
        )?;
        Ok(())
    }
}
