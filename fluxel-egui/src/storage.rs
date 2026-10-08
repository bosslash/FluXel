use std::{collections::BTreeMap, fs, path::Path};

use anyhow::{Context, Result, bail};
use chrono::{Duration, Local, NaiveDate};
use regex::Regex;
use rusqlite::{Connection, OptionalExtension, params};
use uuid::Uuid;

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

    pub fn ensure_tasks(&self) -> Result<()> {
        let conn = Self::connect(&self.paths.tasks_db())?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                importance TEXT,
                created_at TEXT NOT NULL,
                update_at TEXT NOT NULL,
                end_date TEXT,
                status TEXT NOT NULL,
                stored_urls TEXT
            );",
        )?;
        ensure_column(&conn, "tasks", "importance", "TEXT")?;
        ensure_column(&conn, "tasks", "stored_urls", "TEXT")?;
        Ok(())
    }

    pub fn archive_stale_finished(&self, days: u32) -> Result<usize> {
        let cutoff = (Local::now() - Duration::days(i64::from(days.max(1))))
            .format("%Y-%m-%dT%H:%M:%S")
            .to_string();
        let changed = Self::connect(&self.paths.tasks_db())?.execute(
            "UPDATE tasks SET status='archive', update_at=?1
             WHERE lower(trim(status))='finish' AND update_at < ?2",
            params![now_string(), cutoff],
        )?;
        Ok(changed)
    }

    pub fn list_tasks(&self, archive_after_days: u32) -> Result<Vec<Task>> {
        self.archive_stale_finished(archive_after_days)?;
        let conn = Self::connect(&self.paths.tasks_db())?;
        let archive_cutoff = (Local::now() - Duration::days(30))
            .format("%Y-%m-%dT%H:%M:%S")
            .to_string();
        let mut stmt = conn.prepare(
            "SELECT id, name, COALESCE(description,''), COALESCE(importance,''),
                    created_at, update_at, COALESCE(end_date,''), status,
                    COALESCE(stored_urls,'')
             FROM tasks
             WHERE lower(trim(status)) != 'archive' OR update_at >= ?1
             ORDER BY
                CASE lower(trim(status))
                    WHEN 'todo' THEN 1 WHEN 'doing' THEN 2 WHEN 'wait' THEN 3
                    WHEN 'finish' THEN 4 WHEN 'archive' THEN 5 ELSE 99 END,
                CASE WHEN trim(COALESCE(end_date,''))='' THEN 1 ELSE 0 END,
                end_date ASC, created_at DESC",
        )?;
        let rows = stmt.query_map([archive_cutoff], task_from_row)?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn get_task(&self, id: &str) -> Result<Option<Task>> {
        let conn = Self::connect(&self.paths.tasks_db())?;
        conn.query_row(
            "SELECT id, name, COALESCE(description,''), COALESCE(importance,''),
                    created_at, update_at, COALESCE(end_date,''), status,
                    COALESCE(stored_urls,'') FROM tasks WHERE id=?1",
            [id],
            task_from_row,
        )
        .optional()
        .map_err(Into::into)
    }

    pub fn save_task(&self, task: &mut Task) -> Result<()> {
        let now = now_string();
        let conn = Self::connect(&self.paths.tasks_db())?;
        if task.id.is_empty() {
            task.id = Uuid::now_v7().to_string();
            task.created_at = now.clone();
            task.update_at = now;
            if task.status.trim().is_empty() {
                task.status = "todo".to_owned();
            }
            conn.execute(
                "INSERT INTO tasks
                    (id,name,description,importance,created_at,update_at,end_date,status,stored_urls)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",
                params![
                    task.id,
                    task.name,
                    normalize_description(&task.description),
                    task.importance,
                    task.created_at,
                    task.update_at,
                    task.end_date,
                    task.status,
                    task.stored_urls,
                ],
            )?;
        } else {
            task.update_at = now;
            conn.execute(
                "UPDATE tasks SET name=?1, description=?2, importance=?3, end_date=?4,
                    status=?5, update_at=?6, stored_urls=?7 WHERE id=?8",
                params![
                    task.name,
                    normalize_description(&task.description),
                    task.importance,
                    task.end_date,
                    task.status,
                    task.update_at,
                    task.stored_urls,
                    task.id,
                ],
            )?;
        }
        Ok(())
    }

    pub fn delete_task(&self, id: &str) -> Result<()> {
        Self::connect(&self.paths.tasks_db())?.execute("DELETE FROM tasks WHERE id=?1", [id])?;
        Ok(())
    }

    pub fn set_task_status(&self, id: &str, status: &str) -> Result<()> {
        Self::connect(&self.paths.tasks_db())?.execute(
            "UPDATE tasks SET status=?1, update_at=?2 WHERE id=?3",
            params![status, now_string(), id],
        )?;
        Ok(())
    }

    pub fn search_tasks(&self, query: &str, include_archive: bool) -> Result<Vec<Task>> {
        let terms: Vec<String> = query
            .split_whitespace()
            .map(|value| value.to_lowercase())
            .collect();
        let conn = Self::connect(&self.paths.tasks_db())?;
        let mut stmt = conn.prepare(
            "SELECT id, name, COALESCE(description,''), COALESCE(importance,''),
                    created_at, update_at, COALESCE(end_date,''), status,
                    COALESCE(stored_urls,'') FROM tasks ORDER BY update_at DESC",
        )?;
        let mut tasks = stmt
            .query_map([], task_from_row)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        tasks.retain(|task| {
            (include_archive || !task.status.eq_ignore_ascii_case("archive"))
                && terms.iter().all(|term| {
                    task.name.to_lowercase().contains(term)
                        || strip_storage_markers(&task.description)
                            .to_lowercase()
                            .contains(term)
                        || task.importance.to_lowercase().contains(term)
                        || task.status.to_lowercase().contains(term)
                })
        });
        Ok(tasks)
    }

    pub fn dashboard(&self, statuses: &[&str]) -> Result<DashboardSnapshot> {
        let tasks = self.search_tasks("", true)?;
        let today = Local::now().date_naive();
        let week = today + Duration::days(7);
        let mut snapshot = DashboardSnapshot::default();
        let mut deadlines: BTreeMap<NaiveDate, [usize; 4]> = BTreeMap::new();
        for task in tasks {
            if !statuses
                .iter()
                .any(|status| task.status.eq_ignore_ascii_case(status))
            {
                continue;
            }
            let importance = normalized_importance(&task.importance);
            snapshot.importance_counts[importance] += 1;
            snapshot.remaining_total += 1;
            let Ok(date) =
                NaiveDate::parse_from_str(task.end_date.get(..10).unwrap_or(""), "%Y-%m-%d")
            else {
                continue;
            };
            deadlines.entry(date).or_default()[importance] += 1;
            if date < today {
                snapshot.overdue_total += 1;
            }
            if date >= today && date <= week {
                snapshot.due_in_7_days += 1;
            }
        }
        snapshot.deadlines = deadlines.into_iter().collect();
        Ok(snapshot)
    }

    pub fn ensure_quick_access(&self) -> Result<()> {
        let conn = Self::connect(&self.paths.quick_access_db())?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS shortcut_phrases (
                ssid TEXT PRIMARY KEY, title TEXT NOT NULL, value TEXT NOT NULL,
                use_count INTEGER NOT NULL DEFAULT 0, created_date TEXT NOT NULL,
                last_used_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS shortcut_phrase_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ssid TEXT NOT NULL, tag TEXT NOT NULL,
                FOREIGN KEY (ssid) REFERENCES shortcut_phrases(ssid) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS openfile_entries (
                ssid TEXT PRIMARY KEY, title TEXT NOT NULL, value TEXT NOT NULL,
                use_count INTEGER NOT NULL DEFAULT 0, created_date TEXT NOT NULL,
                last_used_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS openfile_entry_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ssid TEXT NOT NULL, tag TEXT NOT NULL,
                FOREIGN KEY (ssid) REFERENCES openfile_entries(ssid) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS quick_access_tags (
                tag TEXT PRIMARY KEY, created_date TEXT NOT NULL
            );",
        )?;
        for table in ["shortcut_phrases", "openfile_entries"] {
            ensure_column(&conn, table, "value", "TEXT")?;
            ensure_column(&conn, table, "use_count", "INTEGER NOT NULL DEFAULT 0")?;
            conn.execute(
                &format!("UPDATE {table} SET value=ssid WHERE value IS NULL OR trim(value)=''"),
                [],
            )?;
        }
        Ok(())
    }

    pub fn quick_access_items(
        &self,
        kind: QuickAccessKind,
        query: &str,
        tag_query: &str,
    ) -> Result<Vec<QuickAccessItem>> {
        let (table, tag_table) = kind.tables();
        let conn = Self::connect(&self.paths.quick_access_db())?;
        let sql = format!(
            "SELECT p.ssid,p.title,p.value,COALESCE(GROUP_CONCAT(DISTINCT t.tag),''),
                    p.use_count,p.last_used_date
             FROM {table} p LEFT JOIN {tag_table} t ON t.ssid=p.ssid
             GROUP BY p.ssid,p.title,p.value,p.use_count,p.created_date,p.last_used_date
             ORDER BY p.use_count DESC,p.last_used_date DESC,p.title COLLATE NOCASE"
        );
        let mut stmt = conn.prepare(&sql)?;
        let mut items = stmt
            .query_map([], |row| {
                Ok(QuickAccessItem {
                    id: row.get(0)?,
                    title: row.get(1)?,
                    value: row.get(2)?,
                    tags: row.get(3)?,
                    use_count: row.get(4)?,
                    last_used_date: row.get(5)?,
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let terms: Vec<String> = query.split_whitespace().map(str::to_lowercase).collect();
        let tag_terms = split_tags(tag_query)
            .into_iter()
            .map(|value| value.to_lowercase())
            .collect::<Vec<_>>();
        items.retain(|item| {
            let title = item.title.to_lowercase();
            let value = item.value.to_lowercase();
            let tags = item.tags.to_lowercase();
            terms
                .iter()
                .all(|term| title.contains(term) || value.contains(term) || tags.contains(term))
                && tag_terms.iter().all(|term| tags.contains(term))
        });
        Ok(items)
    }

    pub fn save_quick_access(
        &self,
        kind: QuickAccessKind,
        item: &mut QuickAccessItem,
    ) -> Result<()> {
        let (table, tag_table) = kind.tables();
        let mut conn = Self::connect(&self.paths.quick_access_db())?;
        let tx = conn.transaction()?;
        if item.id.is_empty() {
            item.id = Uuid::now_v7().to_string();
            let now = now_string();
            tx.execute(
                &format!("INSERT INTO {table}(ssid,title,value,use_count,created_date,last_used_date) VALUES (?1,?2,?3,0,?4,?4)"),
                params![item.id, item.title.trim(), item.value.trim(), now],
            )?;
        } else {
            tx.execute(
                &format!("UPDATE {table} SET title=?1,value=?2 WHERE ssid=?3"),
                params![item.title.trim(), item.value.trim(), item.id],
            )?;
        }
        tx.execute(
            &format!("DELETE FROM {tag_table} WHERE ssid=?1"),
            [&item.id],
        )?;
        for tag in split_tags(&item.tags) {
            tx.execute(
                &format!("INSERT INTO {tag_table}(ssid,tag) VALUES (?1,?2)"),
                params![item.id, tag],
            )?;
            tx.execute(
                "INSERT OR IGNORE INTO quick_access_tags(tag,created_date) VALUES (?1,?2)",
                params![tag, now_string()],
            )?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn delete_quick_access(&self, kind: QuickAccessKind, id: &str) -> Result<()> {
        let (table, tag_table) = kind.tables();
        let mut conn = Self::connect(&self.paths.quick_access_db())?;
        let tx = conn.transaction()?;
        tx.execute(&format!("DELETE FROM {tag_table} WHERE ssid=?1"), [id])?;
        tx.execute(&format!("DELETE FROM {table} WHERE ssid=?1"), [id])?;
        tx.commit()?;
        Ok(())
    }

    pub fn bump_quick_access(&self, kind: QuickAccessKind, id: &str) -> Result<()> {
        let (table, _) = kind.tables();
        Self::connect(&self.paths.quick_access_db())?.execute(
            &format!("UPDATE {table} SET use_count=use_count+1,last_used_date=?1 WHERE ssid=?2"),
            params![now_string(), id],
        )?;
        Ok(())
    }

    pub fn known_tags(&self) -> Result<Vec<String>> {
        let conn = Self::connect(&self.paths.quick_access_db())?;
        let mut stmt = conn.prepare(
            "SELECT tag FROM (
                SELECT tag FROM quick_access_tags UNION
                SELECT tag FROM shortcut_phrase_tags UNION
                SELECT tag FROM openfile_entry_tags
             ) ORDER BY lower(tag),tag",
        )?;
        Ok(stmt
            .query_map([], |row| row.get(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn ensure_gantt(&self) -> Result<()> {
        let conn = Self::connect(&self.paths.planning_db())?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS gantt_projects (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', is_completed INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS gantt_terms (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#2E7BD9', sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES gantt_projects(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_gantt_terms_project
                ON gantt_terms(project_id,sort_order,start_date);",
        )?;
        ensure_column(
            &conn,
            "gantt_projects",
            "description",
            "TEXT NOT NULL DEFAULT ''",
        )?;
        ensure_column(
            &conn,
            "gantt_projects",
            "is_completed",
            "INTEGER NOT NULL DEFAULT 0",
        )?;
        ensure_column(
            &conn,
            "gantt_terms",
            "description",
            "TEXT NOT NULL DEFAULT ''",
        )?;
        Ok(())
    }

    pub fn gantt_projects(&self, include_completed: bool) -> Result<Vec<GanttProject>> {
        let conn = Self::connect(&self.paths.planning_db())?;
        let where_sql = if include_completed {
            ""
        } else {
            "WHERE is_completed=0"
        };
        let mut stmt = conn.prepare(&format!(
            "SELECT id,title,description,is_completed,sort_order FROM gantt_projects
             {where_sql} ORDER BY sort_order,lower(title),id"
        ))?;
        Ok(stmt
            .query_map([], |row| {
                Ok(GanttProject {
                    id: row.get(0)?,
                    title: row.get(1)?,
                    description: row.get(2)?,
                    is_completed: row.get::<_, i64>(3)? != 0,
                    sort_order: row.get(4)?,
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn gantt_terms(&self) -> Result<Vec<GanttTerm>> {
        let conn = Self::connect(&self.paths.planning_db())?;
        let mut stmt = conn.prepare(
            "SELECT id,project_id,title,description,start_date,end_date,color,sort_order
             FROM gantt_terms ORDER BY project_id,sort_order,start_date,lower(title),id",
        )?;
        Ok(stmt
            .query_map([], |row| {
                let start: String = row.get(4)?;
                let end: String = row.get(5)?;
                Ok(GanttTerm {
                    id: row.get(0)?,
                    project_id: row.get(1)?,
                    title: row.get(2)?,
                    description: row.get(3)?,
                    start_date: parse_date(&start),
                    end_date: parse_date(&end),
                    color: row.get(6)?,
                    sort_order: row.get(7)?,
                })
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn save_gantt_project(&self, project: &mut GanttProject) -> Result<()> {
        let conn = Self::connect(&self.paths.planning_db())?;
        if project.id.is_empty() {
            project.id = Uuid::now_v7().to_string();
            project.sort_order = conn.query_row(
                "SELECT COALESCE(MAX(sort_order),-1)+1 FROM gantt_projects",
                [],
                |row| row.get(0),
            )?;
            conn.execute(
                "INSERT INTO gantt_projects(id,title,description,is_completed,sort_order,created_at,updated_at)
                 VALUES (?1,?2,?3,?4,?5,?6,?6)",
                params![project.id, project.title.trim(), project.description.trim(), project.is_completed as i64, project.sort_order, now_string()],
            )?;
        } else {
            conn.execute(
                "UPDATE gantt_projects SET title=?1,description=?2,is_completed=?3,updated_at=?4 WHERE id=?5",
                params![project.title.trim(), project.description.trim(), project.is_completed as i64, now_string(), project.id],
            )?;
        }
        Ok(())
    }

    pub fn delete_gantt_project(&self, id: &str) -> Result<()> {
        Self::connect(&self.paths.planning_db())?
            .execute("DELETE FROM gantt_projects WHERE id=?1", [id])?;
        Ok(())
    }

    pub fn save_gantt_term(&self, term: &mut GanttTerm) -> Result<()> {
        if term.end_date < term.start_date {
            bail!("end date must be on or after start date");
        }
        let conn = Self::connect(&self.paths.planning_db())?;
        if term.id.is_empty() {
            term.id = Uuid::now_v7().to_string();
            term.sort_order = conn.query_row(
                "SELECT COALESCE(MAX(sort_order),-1)+1 FROM gantt_terms WHERE project_id=?1",
                [&term.project_id],
                |row| row.get(0),
            )?;
            conn.execute(
                "INSERT INTO gantt_terms
                    (id,project_id,title,description,start_date,end_date,color,sort_order,created_at,updated_at)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?9)",
                params![term.id, term.project_id, term.title.trim(), term.description.trim(), term.start_date.to_string(), term.end_date.to_string(), term.color, term.sort_order, now_string()],
            )?;
        } else {
            conn.execute(
                "UPDATE gantt_terms SET project_id=?1,title=?2,description=?3,start_date=?4,
                    end_date=?5,color=?6,updated_at=?7 WHERE id=?8",
                params![
                    term.project_id,
                    term.title.trim(),
                    term.description.trim(),
                    term.start_date.to_string(),
                    term.end_date.to_string(),
                    term.color,
                    now_string(),
                    term.id
                ],
            )?;
        }
        Ok(())
    }

    pub fn delete_gantt_term(&self, id: &str) -> Result<()> {
        Self::connect(&self.paths.planning_db())?
            .execute("DELETE FROM gantt_terms WHERE id=?1", [id])?;
        Ok(())
    }
}

fn task_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Task> {
    Ok(Task {
        id: row.get(0)?,
        name: row.get(1)?,
        description: row.get(2)?,
        importance: row.get(3)?,
        created_at: row.get(4)?,
        update_at: row.get(5)?,
        end_date: row.get(6)?,
        status: row.get(7)?,
        stored_urls: row.get(8)?,
    })
}

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

fn now_string() -> String {
    Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()
}

fn parse_date(value: &str) -> NaiveDate {
    NaiveDate::parse_from_str(value.get(..10).unwrap_or(value), "%Y-%m-%d")
        .unwrap_or_else(|_| Local::now().date_naive())
}

pub fn split_tags(raw: &str) -> Vec<String> {
    let mut result = Vec::new();
    for value in raw
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        if !result
            .iter()
            .any(|existing: &String| existing.eq_ignore_ascii_case(value))
        {
            result.push(value.to_owned());
        }
    }
    result
}

pub fn strip_storage_markers(value: &str) -> String {
    let file_re = Regex::new(r"\\file\|((?:\\.|[^|])+)\|").expect("valid file marker regex");
    let url_re = Regex::new(r#"(?i)\\url:(https?://[^\s<>"“”]+)"#).expect("valid url marker regex");
    let files = file_re.replace_all(value, |caps: &regex::Captures<'_>| {
        caps[1].replace(r"\|", "|")
    });
    url_re.replace_all(&files, "$1").into_owned()
}

pub fn normalize_description(value: &str) -> String {
    // Preserve the Python storage convention for URLs. Existing file markers are kept intact.
    let stored_url_re =
        Regex::new(r#"(?i)\\url:(https?://[^\s<>"“”]+)"#).expect("valid stored URL regex");
    let plain = stored_url_re.replace_all(value, "$1");
    let url_re = Regex::new(r#"(?i)https?://[^\s<>"“”]+"#).expect("valid url regex");
    url_re
        .replace_all(&plain, |caps: &regex::Captures<'_>| {
            format!(r"\url:{}", &caps[0])
        })
        .into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_storage() -> (tempfile::TempDir, Storage) {
        let temp = tempfile::tempdir().unwrap();
        let paths = AppPaths {
            state_dir: temp.path().to_owned(),
            database_dir: temp.path().to_owned(),
            settings_file: temp.path().join("settings.ini"),
        };
        let storage = Storage::new(paths).unwrap();
        (temp, storage)
    }

    #[test]
    fn creates_python_compatible_databases() {
        let (_temp, storage) = test_storage();
        let conn = Connection::open(storage.paths.tasks_db()).unwrap();
        let columns = conn
            .prepare("PRAGMA table_info(tasks)")
            .unwrap()
            .query_map([], |row| row.get::<_, String>(1))
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap();
        assert_eq!(
            columns,
            [
                "id",
                "name",
                "description",
                "importance",
                "created_at",
                "update_at",
                "end_date",
                "status",
                "stored_urls"
            ]
        );
    }

    #[test]
    fn task_round_trip_keeps_schema_values() {
        let (_temp, storage) = test_storage();
        let mut task = Task {
            name: "移植確認".to_owned(),
            description: "https://example.com".to_owned(),
            importance: "高".to_owned(),
            end_date: "2030-01-02".to_owned(),
            status: "todo".to_owned(),
            ..Task::default()
        };
        storage.save_task(&mut task).unwrap();
        let loaded = storage.get_task(&task.id).unwrap().unwrap();
        assert_eq!(loaded.name, "移植確認");
        assert_eq!(loaded.description, r"\url:https://example.com");
        assert_eq!(loaded.importance, "高");
    }

    #[test]
    fn quick_access_round_trip_preserves_tags() {
        let (_temp, storage) = test_storage();
        let mut item = QuickAccessItem {
            title: "Docs".to_owned(),
            value: "https://example.com".to_owned(),
            tags: "work, docs,WORK".to_owned(),
            ..QuickAccessItem::default()
        };
        storage
            .save_quick_access(QuickAccessKind::Shortcut, &mut item)
            .unwrap();
        let rows = storage
            .quick_access_items(QuickAccessKind::Shortcut, "Docs", "work")
            .unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(split_tags(&rows[0].tags).len(), 2);
    }

    #[test]
    fn gantt_rejects_reverse_range() {
        let (_temp, storage) = test_storage();
        let mut project = GanttProject {
            title: "P".to_owned(),
            ..GanttProject::default()
        };
        storage.save_gantt_project(&mut project).unwrap();
        let mut term = GanttTerm {
            id: String::new(),
            project_id: project.id,
            title: "T".to_owned(),
            description: String::new(),
            start_date: NaiveDate::from_ymd_opt(2030, 2, 2).unwrap(),
            end_date: NaiveDate::from_ymd_opt(2030, 2, 1).unwrap(),
            color: "#2E7BD9".to_owned(),
            sort_order: 0,
        };
        assert!(storage.save_gantt_term(&mut term).is_err());
    }

    #[test]
    fn exports_consistent_tasks_backup() {
        let (temp, storage) = test_storage();
        let mut task = Task {
            name: "backup".to_owned(),
            status: "todo".to_owned(),
            ..Task::default()
        };
        storage.save_task(&mut task).unwrap();
        let destination = temp.path().join("exports").join("Tasks-copy.db");
        storage.export_tasks_db(&destination).unwrap();
        let count: i64 = Connection::open(destination)
            .unwrap()
            .query_row("SELECT COUNT(*) FROM tasks", [], |row| row.get(0))
            .unwrap();
        assert_eq!(count, 1);
    }

    #[test]
    fn marker_helpers_match_existing_format() {
        assert_eq!(
            normalize_description("open https://example.com/a"),
            r"open \url:https://example.com/a"
        );
        assert_eq!(
            strip_storage_markers(r"open \url:https://example.com/a"),
            "open https://example.com/a"
        );
        assert_eq!(
            normalize_description(r"read \file|C:\Docs\a.txt|"),
            r"read \file|C:\Docs\a.txt|"
        );
    }
}
