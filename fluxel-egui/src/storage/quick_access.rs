//! Shortcut, OpenFile, usage-count, and shared-tag persistence.

use super::*;

impl Storage {
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
            let tags = split_tags(&item.tags)
                .into_iter()
                .map(|tag| tag.to_lowercase())
                .collect::<Vec<_>>();
            terms.iter().all(|term| {
                title.contains(term)
                    || value.contains(term)
                    || tags.iter().any(|tag| tag.contains(term))
            }) && tag_terms
                .iter()
                .all(|term| tags.iter().any(|tag| tag.contains(term)))
        });
        let query = query.trim().to_lowercase();
        items.sort_by(|left, right| {
            quick_access_sort_key(left, &query).cmp(&quick_access_sort_key(right, &query))
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

    /// Adds one or more comma-separated reusable tags without changing saved items.
    pub fn add_known_tags(&self, raw: &str) -> Result<()> {
        let conn = Self::connect(&self.paths.quick_access_db())?;
        let now = now_string();
        for tag in split_tags(raw) {
            conn.execute(
                "INSERT OR IGNORE INTO quick_access_tags(tag,created_date) VALUES (?1,?2)",
                params![tag, now],
            )?;
        }
        Ok(())
    }

    /// Deletes a tag from the catalog and from every shortcut/open-file item.
    pub fn delete_known_tag(&self, tag: &str) -> Result<()> {
        let tag = tag.trim();
        if tag.is_empty() {
            return Ok(());
        }
        let mut conn = Self::connect(&self.paths.quick_access_db())?;
        let tx = conn.transaction()?;
        tx.execute("DELETE FROM quick_access_tags WHERE tag=?1", [tag])?;
        tx.execute("DELETE FROM shortcut_phrase_tags WHERE tag=?1", [tag])?;
        tx.execute("DELETE FROM openfile_entry_tags WHERE tag=?1", [tag])?;
        tx.commit()?;
        Ok(())
    }
}

fn quick_access_sort_key(
    item: &QuickAccessItem,
    query: &str,
) -> (
    u8,
    std::cmp::Reverse<i64>,
    std::cmp::Reverse<String>,
    String,
) {
    let title = item.title.to_lowercase();
    let value = item.value.to_lowercase();
    let rank = if query.is_empty() || title == query {
        0
    } else if title.starts_with(query) {
        1
    } else if value.starts_with(query) {
        2
    } else {
        3
    };
    (
        rank,
        std::cmp::Reverse(item.use_count),
        std::cmp::Reverse(item.last_used_date.clone()),
        title,
    )
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
