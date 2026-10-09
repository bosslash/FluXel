//! Mapping between the three SQLite databases and stable sync items.

use std::collections::HashMap;

use anyhow::{Result, bail};
use rusqlite::{Connection, Row, params};
use serde_json::{Map, Value};

use crate::{paths::AppPaths, storage::Storage};

use super::types::{SyncEvent, SyncItem};

pub struct LocalRepository<'a> {
    storage: &'a Storage,
}

impl<'a> LocalRepository<'a> {
    pub fn new(storage: &'a Storage) -> Self {
        Self { storage }
    }

    pub fn collect_items(&self) -> Result<HashMap<String, SyncItem>> {
        self.storage.ensure_all()?;
        let mut items = HashMap::new();
        for item in self.collect_tasks()? {
            items.insert(item.key(), item);
        }
        for item in self.collect_quick_access()? {
            items.insert(item.key(), item);
        }
        for item in self.collect_gantt()? {
            items.insert(item.key(), item);
        }
        Ok(items)
    }

    pub fn apply_event(&self, event: &SyncEvent) -> Result<()> {
        if event.operation == "delete" {
            return self.delete(&event.kind, &event.entity_id);
        }
        let Some(data) = event.data.as_ref() else {
            bail!("sync upsert has no payload: {}", event.key());
        };
        match event.kind.as_str() {
            "task" => self.upsert_task(data),
            "shortcut" => self.upsert_quick("shortcut_phrases", "shortcut_phrase_tags", data),
            "openfile" => self.upsert_quick("openfile_entries", "openfile_entry_tags", data),
            "tag" => self.upsert_tag(data),
            "gantt_project" => self.upsert_project(data),
            "gantt_term" => self.upsert_term(data),
            other => bail!("unsupported sync item type: {other}"),
        }
    }

    fn collect_tasks(&self) -> Result<Vec<SyncItem>> {
        let connection = Connection::open(self.storage.paths.tasks_db())?;
        let mut statement = connection.prepare(
            "SELECT id,name,description,importance,created_at,update_at,end_date,status,stored_urls
             FROM tasks ORDER BY id",
        )?;
        Ok(statement
            .query_map([], |row| {
                let data = object(
                    row,
                    &[
                        ("id", 0, false),
                        ("name", 1, false),
                        ("description", 2, false),
                        ("importance", 3, false),
                        ("created_at", 4, false),
                        ("update_at", 5, false),
                        ("end_date", 6, false),
                        ("status", 7, false),
                        ("stored_urls", 8, false),
                    ],
                )?;
                Ok(SyncItem {
                    kind: "task".to_owned(),
                    entity_id: string(&data, "id"),
                    data,
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?)
    }

    fn collect_quick_access(&self) -> Result<Vec<SyncItem>> {
        let connection = Connection::open(self.storage.paths.quick_access_db())?;
        let mut result = Vec::new();
        for (kind, table, tag_table) in [
            ("shortcut", "shortcut_phrases", "shortcut_phrase_tags"),
            ("openfile", "openfile_entries", "openfile_entry_tags"),
        ] {
            let mut statement = connection.prepare(&format!(
                "SELECT ssid,title,value,use_count,created_date,last_used_date FROM {table} ORDER BY ssid"
            ))?;
            let rows = statement
                .query_map([], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, i64>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, String>(5)?,
                    ))
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?;
            for (id, title, value, use_count, created_date, last_used_date) in rows {
                let tags = connection
                    .prepare(&format!(
                        "SELECT tag FROM {tag_table} WHERE ssid=?1 ORDER BY lower(tag),tag"
                    ))?
                    .query_map([&id], |row| row.get::<_, String>(0))?
                    .collect::<rusqlite::Result<Vec<_>>>()?;
                let mut data = Map::new();
                data.insert("ssid".to_owned(), Value::String(id.clone()));
                data.insert("title".to_owned(), Value::String(title));
                data.insert("value".to_owned(), Value::String(value));
                data.insert("use_count".to_owned(), use_count.into());
                data.insert("created_date".to_owned(), Value::String(created_date));
                data.insert("last_used_date".to_owned(), Value::String(last_used_date));
                data.insert(
                    "tags".to_owned(),
                    Value::Array(tags.into_iter().map(Value::String).collect()),
                );
                result.push(SyncItem {
                    kind: kind.to_owned(),
                    entity_id: id,
                    data,
                });
            }
        }
        let mut statement = connection
            .prepare("SELECT tag,created_date FROM quick_access_tags ORDER BY lower(tag),tag")?;
        for row in statement.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })? {
            let (tag, created_date) = row?;
            let mut data = Map::new();
            data.insert("tag".to_owned(), Value::String(tag.clone()));
            data.insert("created_date".to_owned(), Value::String(created_date));
            result.push(SyncItem {
                kind: "tag".to_owned(),
                entity_id: tag,
                data,
            });
        }
        Ok(result)
    }

    fn collect_gantt(&self) -> Result<Vec<SyncItem>> {
        let connection = Connection::open(self.storage.paths.planning_db())?;
        let mut result = Vec::new();
        let mut projects = connection.prepare(
            "SELECT id,title,description,is_completed,sort_order,created_at,updated_at
             FROM gantt_projects ORDER BY id",
        )?;
        for row in projects.query_map([], |row| {
            object(
                row,
                &[
                    ("id", 0, false),
                    ("title", 1, false),
                    ("description", 2, false),
                    ("is_completed", 3, true),
                    ("sort_order", 4, true),
                    ("created_at", 5, false),
                    ("updated_at", 6, false),
                ],
            )
        })? {
            let data = row?;
            result.push(SyncItem {
                kind: "gantt_project".to_owned(),
                entity_id: string(&data, "id"),
                data,
            });
        }
        let mut terms = connection.prepare(
            "SELECT id,project_id,title,description,start_date,end_date,color,sort_order,created_at,updated_at
             FROM gantt_terms ORDER BY id",
        )?;
        for row in terms.query_map([], |row| {
            object(
                row,
                &[
                    ("id", 0, false),
                    ("project_id", 1, false),
                    ("title", 2, false),
                    ("description", 3, false),
                    ("start_date", 4, false),
                    ("end_date", 5, false),
                    ("color", 6, false),
                    ("sort_order", 7, true),
                    ("created_at", 8, false),
                    ("updated_at", 9, false),
                ],
            )
        })? {
            let data = row?;
            result.push(SyncItem {
                kind: "gantt_term".to_owned(),
                entity_id: string(&data, "id"),
                data,
            });
        }
        Ok(result)
    }

    fn upsert_task(&self, data: &Map<String, Value>) -> Result<()> {
        Connection::open(self.storage.paths.tasks_db())?.execute(
            "INSERT INTO tasks(id,name,description,importance,created_at,update_at,end_date,status,stored_urls)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)
             ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,
             importance=excluded.importance,created_at=excluded.created_at,
             update_at=excluded.update_at,end_date=excluded.end_date,status=excluded.status,
             stored_urls=excluded.stored_urls",
            params![string(data,"id"), string(data,"name"), optional_string(data,"description"),
                optional_string(data,"importance"), string(data,"created_at"),
                string(data,"update_at"), optional_string(data,"end_date"),
                string(data,"status"), optional_string(data,"stored_urls")],
        )?;
        Ok(())
    }

    fn upsert_quick(&self, table: &str, tag_table: &str, data: &Map<String, Value>) -> Result<()> {
        let mut connection = Connection::open(self.storage.paths.quick_access_db())?;
        let transaction = connection.transaction()?;
        let id = string(data, "ssid");
        transaction.execute(
            &format!(
                "INSERT INTO {table}(ssid,title,value,use_count,created_date,last_used_date)
                VALUES (?1,?2,?3,?4,?5,?6) ON CONFLICT(ssid) DO UPDATE SET
                title=excluded.title,value=excluded.value,use_count=excluded.use_count,
                created_date=excluded.created_date,last_used_date=excluded.last_used_date"
            ),
            params![
                id,
                string(data, "title"),
                string(data, "value"),
                integer(data, "use_count"),
                string(data, "created_date"),
                string(data, "last_used_date")
            ],
        )?;
        transaction.execute(&format!("DELETE FROM {tag_table} WHERE ssid=?1"), [&id])?;
        for tag in data
            .get("tags")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let Some(tag) = tag.as_str().filter(|tag| !tag.trim().is_empty()) else {
                continue;
            };
            transaction.execute(
                &format!("INSERT INTO {tag_table}(ssid,tag) VALUES (?1,?2)"),
                params![id, tag],
            )?;
            transaction.execute(
                "INSERT OR IGNORE INTO quick_access_tags(tag,created_date) VALUES (?1,?2)",
                params![tag, string(data, "created_date")],
            )?;
        }
        transaction.commit()?;
        Ok(())
    }

    fn upsert_tag(&self, data: &Map<String, Value>) -> Result<()> {
        Connection::open(self.storage.paths.quick_access_db())?.execute(
            "INSERT INTO quick_access_tags(tag,created_date) VALUES (?1,?2)
             ON CONFLICT(tag) DO UPDATE SET created_date=excluded.created_date",
            params![string(data, "tag"), string(data, "created_date")],
        )?;
        Ok(())
    }

    fn upsert_project(&self, data: &Map<String, Value>) -> Result<()> {
        Connection::open(self.storage.paths.planning_db())?.execute(
            "INSERT INTO gantt_projects(id,title,description,is_completed,sort_order,created_at,updated_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7) ON CONFLICT(id) DO UPDATE SET
             title=excluded.title,description=excluded.description,is_completed=excluded.is_completed,
             sort_order=excluded.sort_order,created_at=excluded.created_at,updated_at=excluded.updated_at",
            params![string(data,"id"),string(data,"title"),string(data,"description"),
                integer(data,"is_completed"),integer(data,"sort_order"),
                string(data,"created_at"),string(data,"updated_at")],
        )?;
        Ok(())
    }

    fn upsert_term(&self, data: &Map<String, Value>) -> Result<()> {
        let connection = Connection::open(self.storage.paths.planning_db())?;
        connection.execute_batch("PRAGMA foreign_keys=ON")?;
        connection.execute(
            "INSERT INTO gantt_terms(id,project_id,title,description,start_date,end_date,color,sort_order,created_at,updated_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10) ON CONFLICT(id) DO UPDATE SET
             project_id=excluded.project_id,title=excluded.title,description=excluded.description,
             start_date=excluded.start_date,end_date=excluded.end_date,color=excluded.color,
             sort_order=excluded.sort_order,created_at=excluded.created_at,updated_at=excluded.updated_at",
            params![string(data,"id"),string(data,"project_id"),string(data,"title"),
                string(data,"description"),string(data,"start_date"),string(data,"end_date"),
                string(data,"color"),integer(data,"sort_order"),string(data,"created_at"),
                string(data,"updated_at")],
        )?;
        Ok(())
    }

    fn delete(&self, kind: &str, id: &str) -> Result<()> {
        let paths: &AppPaths = &self.storage.paths;
        match kind {
            "task" => {
                Connection::open(paths.tasks_db())?
                    .execute("DELETE FROM tasks WHERE id=?1", [id])?;
            }
            "shortcut" | "openfile" => {
                let (table, tags) = if kind == "shortcut" {
                    ("shortcut_phrases", "shortcut_phrase_tags")
                } else {
                    ("openfile_entries", "openfile_entry_tags")
                };
                let mut connection = Connection::open(paths.quick_access_db())?;
                let transaction = connection.transaction()?;
                transaction.execute(&format!("DELETE FROM {tags} WHERE ssid=?1"), [id])?;
                transaction.execute(&format!("DELETE FROM {table} WHERE ssid=?1"), [id])?;
                transaction.commit()?;
            }
            "tag" => {
                let connection = Connection::open(paths.quick_access_db())?;
                connection.execute("DELETE FROM quick_access_tags WHERE tag=?1", [id])?;
                connection.execute("DELETE FROM shortcut_phrase_tags WHERE tag=?1", [id])?;
                connection.execute("DELETE FROM openfile_entry_tags WHERE tag=?1", [id])?;
            }
            "gantt_project" | "gantt_term" => {
                let connection = Connection::open(paths.planning_db())?;
                connection.execute_batch("PRAGMA foreign_keys=ON")?;
                let table = if kind == "gantt_project" {
                    "gantt_projects"
                } else {
                    "gantt_terms"
                };
                connection.execute(&format!("DELETE FROM {table} WHERE id=?1"), [id])?;
            }
            other => bail!("unsupported sync item type: {other}"),
        }
        Ok(())
    }
}

fn object(row: &Row<'_>, fields: &[(&str, usize, bool)]) -> rusqlite::Result<Map<String, Value>> {
    let mut result = Map::new();
    for (name, index, integer_value) in fields {
        let value = if *integer_value {
            row.get::<_, Option<i64>>(*index)?
                .map(Value::from)
                .unwrap_or(Value::Null)
        } else {
            row.get::<_, Option<String>>(*index)?
                .map(Value::String)
                .unwrap_or(Value::Null)
        };
        result.insert((*name).to_owned(), value);
    }
    Ok(result)
}

fn string(data: &Map<String, Value>, key: &str) -> String {
    data.get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned()
}

fn optional_string(data: &Map<String, Value>, key: &str) -> Option<String> {
    data.get(key).and_then(Value::as_str).map(str::to_owned)
}

fn integer(data: &Map<String, Value>, key: &str) -> i64 {
    data.get(key).and_then(Value::as_i64).unwrap_or_default()
}
