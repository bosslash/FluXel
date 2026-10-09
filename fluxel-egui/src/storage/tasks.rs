//! Task persistence, task search, dashboard aggregation, and text markers.

use super::*;

impl Storage {
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

    /// Searches tasks with the same filters and ranking used by the Python client.
    pub fn search_tasks(
        &self,
        query: &str,
        include_archive: bool,
        status_filter: &str,
        importance_filter: &str,
    ) -> Result<Vec<Task>> {
        let terms: Vec<String> = query
            .split_whitespace()
            .map(|value| value.to_lowercase())
            .collect();
        let status_filter = status_filter.trim().to_lowercase();
        let importance_filter = importance_filter.trim().to_lowercase();
        let importance_aliases = match importance_filter.as_str() {
            "high" => vec!["高", "high"],
            "medium" => vec!["中", "medium", "normal"],
            "low" => vec!["低", "low"],
            "" => Vec::new(),
            value => vec![value],
        };
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
            (if status_filter.is_empty() {
                include_archive || !task.status.eq_ignore_ascii_case("archive")
            } else {
                task.status.trim().eq_ignore_ascii_case(&status_filter)
            }) && (importance_aliases.is_empty()
                || importance_aliases
                    .iter()
                    .any(|alias| task.importance.trim().eq_ignore_ascii_case(alias)))
                && terms.iter().all(|term| {
                    task.name.to_lowercase().contains(term)
                        || strip_storage_markers(&task.description)
                            .to_lowercase()
                            .contains(term)
                })
        });
        tasks.sort_by(|left, right| {
            let left_title = left.name.to_lowercase();
            let right_title = right.name.to_lowercase();
            let left_title_match = terms.iter().all(|term| left_title.contains(term));
            let right_title_match = terms.iter().all(|term| right_title.contains(term));
            task_search_sort_key(left, left_title_match)
                .cmp(&task_search_sort_key(right, right_title_match))
        });
        Ok(tasks)
    }

    pub fn dashboard(&self, statuses: &[&str]) -> Result<DashboardSnapshot> {
        let tasks = self.search_tasks("", true, "", "")?;
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
            let date_text = task.end_date.get(..10).unwrap_or("").replace('/', "-");
            let Ok(date) = NaiveDate::parse_from_str(&date_text, "%Y-%m-%d") else {
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
}

fn task_search_sort_key(task: &Task, title_match: bool) -> (u8, u8, String, String, String) {
    let archive = u8::from(task.status.trim().eq_ignore_ascii_case("archive"));
    let end_date = if task.end_date.trim().is_empty() {
        "9999-99-99".to_owned()
    } else {
        task.end_date
            .chars()
            .take(10)
            .collect::<String>()
            .replace('/', "-")
    };
    (
        u8::from(!title_match),
        archive,
        end_date,
        task.name.to_lowercase(),
        task.id.clone(),
    )
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
