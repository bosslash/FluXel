//! Gantt project and term persistence, ordering, and date movement.

use super::*;

impl Storage {
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

    /// Moves a term while preserving its duration.
    pub fn move_gantt_term_days(&self, id: &str, days: i64) -> Result<bool> {
        let conn = Self::connect(&self.paths.planning_db())?;
        let dates = conn
            .query_row(
                "SELECT start_date,end_date FROM gantt_terms WHERE id=?1",
                [id],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?;
        let Some((start, end)) = dates else {
            return Ok(false);
        };
        let start = parse_date(&start) + Duration::days(days);
        let end = parse_date(&end) + Duration::days(days);
        conn.execute(
            "UPDATE gantt_terms SET start_date=?1,end_date=?2,updated_at=?3 WHERE id=?4",
            params![start.to_string(), end.to_string(), now_string(), id],
        )?;
        Ok(true)
    }

    /// Swaps a term with its adjacent sibling and normalizes sibling order.
    pub fn reorder_gantt_term(&self, id: &str, direction: isize) -> Result<bool> {
        let mut conn = Self::connect(&self.paths.planning_db())?;
        let project_id = conn
            .query_row(
                "SELECT project_id FROM gantt_terms WHERE id=?1",
                [id],
                |row| row.get::<_, String>(0),
            )
            .optional()?;
        let Some(project_id) = project_id else {
            return Ok(false);
        };
        let mut statement = conn.prepare(
            "SELECT id FROM gantt_terms WHERE project_id=?1
             ORDER BY sort_order,start_date,lower(title),id",
        )?;
        let mut ids = statement
            .query_map([project_id], |row| row.get::<_, String>(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        drop(statement);
        let Some(index) = ids.iter().position(|candidate| candidate == id) else {
            return Ok(false);
        };
        let target = index as isize + direction.signum();
        if !(0..ids.len() as isize).contains(&target) {
            return Ok(false);
        }
        ids.swap(index, target as usize);
        let tx = conn.transaction()?;
        let now = now_string();
        for (sort_order, term_id) in ids.iter().enumerate() {
            tx.execute(
                "UPDATE gantt_terms SET sort_order=?1,updated_at=?2 WHERE id=?3",
                params![sort_order as i64, now, term_id],
            )?;
        }
        tx.commit()?;
        Ok(true)
    }

    /// Moves a term to the end of another project.
    pub fn move_gantt_term_to_project(&self, id: &str, project_id: &str) -> Result<bool> {
        let conn = Self::connect(&self.paths.planning_db())?;
        let current = conn
            .query_row(
                "SELECT project_id FROM gantt_terms WHERE id=?1",
                [id],
                |row| row.get::<_, String>(0),
            )
            .optional()?;
        if current
            .as_deref()
            .is_none_or(|current| current == project_id)
        {
            return Ok(false);
        }
        let target_exists = conn
            .query_row(
                "SELECT 1 FROM gantt_projects WHERE id=?1",
                [project_id],
                |_| Ok(()),
            )
            .optional()?
            .is_some();
        if !target_exists {
            return Ok(false);
        }
        let next_order: i64 = conn.query_row(
            "SELECT COALESCE(MAX(sort_order),-1)+1 FROM gantt_terms WHERE project_id=?1",
            [project_id],
            |row| row.get(0),
        )?;
        conn.execute(
            "UPDATE gantt_terms SET project_id=?1,sort_order=?2,updated_at=?3 WHERE id=?4",
            params![project_id, next_order, now_string(), id],
        )?;
        Ok(true)
    }
}

fn parse_date(value: &str) -> NaiveDate {
    NaiveDate::parse_from_str(
        &value.get(..10).unwrap_or(value).replace('/', "-"),
        "%Y-%m-%d",
    )
    .unwrap_or_else(|_| Local::now().date_naive())
}
