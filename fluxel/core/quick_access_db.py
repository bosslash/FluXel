"""QuickAccess 用 SQLite（ShortCut/OpenFile 項目管理）。"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
import re

from fluxel.paths import local_app_data_dir


def quick_access_db_path() -> Path:
    return local_app_data_dir() / "QuickAccess.db"


def ensure_quick_access_tables() -> None:
    conn = sqlite3.connect(str(quick_access_db_path()))
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    # 新規スキーマ: ShortCut Phrase / OpenFile（タグは別テーブル）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shortcut_phrases (
            ssid TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            value TEXT NOT NULL,
            use_count INTEGER NOT NULL DEFAULT 0,
            created_date TEXT NOT NULL,
            last_used_date TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shortcut_phrase_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ssid TEXT NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (ssid) REFERENCES shortcut_phrases(ssid) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS openfile_entries (
            ssid TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            value TEXT NOT NULL,
            use_count INTEGER NOT NULL DEFAULT 0,
            created_date TEXT NOT NULL,
            last_used_date TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS openfile_entry_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ssid TEXT NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (ssid) REFERENCES openfile_entries(ssid) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS quick_access_tags (
            tag TEXT PRIMARY KEY,
            created_date TEXT NOT NULL
        )
        """
    )
    _ensure_item_columns(cur, "shortcut_phrases")
    _ensure_item_columns(cur, "openfile_entries")
    conn.commit()
    conn.close()


def _ensure_item_columns(cur: sqlite3.Cursor, table: str) -> None:
    """v0.2 の「値=主キー」形式を、編集可能な独立カラムへ安全に移行する。"""
    cur.execute(f"PRAGMA table_info({table})")
    columns = {str(row[1]) for row in cur.fetchall()}
    if "value" not in columns:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN value TEXT")
    if "use_count" not in columns:
        cur.execute(
            f"ALTER TABLE {table} ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0"
        )
    cur.execute(
        f"UPDATE {table} SET value = ssid WHERE value IS NULL OR trim(value) = ''"
    )


def search_shortcut_items(query: str, tag_query: str = "") -> list[tuple]:
    return _search_items("shortcut_phrases", "shortcut_phrase_tags", query, tag_query)


def search_openfile_items(query: str, tag_query: str = "") -> list[tuple]:
    return _search_items("openfile_entries", "openfile_entry_tags", query, tag_query)


def add_shortcut_item(title: str, command: str, tags: str) -> str:
    return _add_item("shortcut_phrases", "shortcut_phrase_tags", title, command, tags)


def add_openfile_item(title: str, file_path: str, tags: str) -> str:
    return _add_item("openfile_entries", "openfile_entry_tags", title, file_path, tags)


def update_shortcut_item(item_id: str, title: str, command: str, tags: str) -> None:
    _update_item("shortcut_phrases", "shortcut_phrase_tags", item_id, title, command, tags)


def update_openfile_item(item_id: str, title: str, file_path: str, tags: str) -> None:
    _update_item("openfile_entries", "openfile_entry_tags", item_id, title, file_path, tags)


def delete_shortcut_item(item_id: str) -> None:
    _delete_item("shortcut_phrases", "shortcut_phrase_tags", item_id)


def delete_openfile_item(item_id: str) -> None:
    _delete_item("openfile_entries", "openfile_entry_tags", item_id)


def bump_shortcut_use_count(item_id: str) -> None:
    _bump_use_count("shortcut_phrases", item_id)


def bump_openfile_use_count(item_id: str) -> None:
    _bump_use_count("openfile_entries", item_id)


def list_known_tags() -> list[str]:
    conn = sqlite3.connect(str(quick_access_db_path()))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT tag FROM (
            SELECT tag FROM quick_access_tags
            UNION
            SELECT tag FROM shortcut_phrase_tags
            UNION
            SELECT tag FROM openfile_entry_tags
        )
        ORDER BY lower(tag) ASC, tag ASC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [str(r[0]) for r in rows if r and str(r[0]).strip()]


def add_known_tag(tag: str) -> None:
    parts = _split_tags(tag)
    if not parts:
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(str(quick_access_db_path()))
    cur = conn.cursor()
    for p in parts:
        cur.execute(
            "INSERT OR IGNORE INTO quick_access_tags(tag, created_date) VALUES (?, ?)",
            (p, now),
        )
    conn.commit()
    conn.close()


def delete_known_tag(tag: str) -> None:
    t = (tag or "").strip()
    if not t:
        return
    conn = sqlite3.connect(str(quick_access_db_path()))
    cur = conn.cursor()
    cur.execute("DELETE FROM quick_access_tags WHERE tag = ?", (t,))
    cur.execute("DELETE FROM shortcut_phrase_tags WHERE tag = ?", (t,))
    cur.execute("DELETE FROM openfile_entry_tags WHERE tag = ?", (t,))
    conn.commit()
    conn.close()


def _search_items(table: str, tag_table: str, query: str, tag_query: str) -> list[tuple]:
    conn = sqlite3.connect(str(quick_access_db_path()))
    cur = conn.cursor()
    q = (query or "").strip().lower()
    query_terms = [term for term in re.split(r"\s+", q) if term]
    tag_terms = [t.lower() for t in _split_tags(tag_query)]
    select_sql = f"""
        SELECT p.ssid, p.title, p.value,
               COALESCE(GROUP_CONCAT(DISTINCT t.tag), '') AS tags,
               p.use_count, p.last_used_date
        FROM {table} p
        LEFT JOIN {tag_table} t ON t.ssid = p.ssid
    """
    where_parts: list[str] = []
    params: list[str] = []
    for term in query_terms:
        like = f"%{_escape_like(term)}%"
        where_parts.append(
            f"""(
                lower(p.title) LIKE ? ESCAPE '\\'
                OR lower(p.value) LIKE ? ESCAPE '\\'
                OR EXISTS (
                    SELECT 1 FROM {tag_table} qt
                    WHERE qt.ssid = p.ssid
                      AND lower(qt.tag) LIKE ? ESCAPE '\\'
                )
            )"""
        )
        params.extend((like, like, like))
    for term in tag_terms:
        where_parts.append(
            f"""EXISTS (
                SELECT 1 FROM {tag_table} tt
                WHERE tt.ssid = p.ssid
                  AND lower(tt.tag) LIKE ? ESCAPE '\\'
            )"""
        )
        params.append(f"%{_escape_like(term)}%")
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    rank_params: list[str] = []
    if q:
        order_sql = """
        ORDER BY
            CASE
                WHEN lower(p.title) = ? THEN 0
                WHEN lower(p.title) LIKE ? ESCAPE '\\' THEN 1
                WHEN lower(p.value) LIKE ? ESCAPE '\\' THEN 2
                ELSE 3
            END ASC,
            p.use_count DESC,
            p.last_used_date DESC,
            p.title COLLATE NOCASE ASC
        """
        rank_params = [q, f"{_escape_like(q)}%", f"{_escape_like(q)}%"]
    else:
        order_sql = """
        ORDER BY p.use_count DESC, p.last_used_date DESC, p.title COLLATE NOCASE ASC
        """
    cur.execute(
        select_sql
        + f"""
        {where_sql}
        GROUP BY p.ssid, p.title, p.value, p.use_count, p.created_date, p.last_used_date
        {order_sql}
        """,
        tuple(params + rank_params),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def _add_item(table: str, tag_table: str, title: str, value: str, tags: str) -> str:
    item_id = str(uuid.uuid7())
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(str(quick_access_db_path()))
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO {table}(ssid, title, value, use_count, created_date, last_used_date)
        VALUES (?, ?, ?, 0, ?, ?)
        """,
        (item_id, title.strip(), value.strip(), now, now),
    )
    _replace_tags(cur, tag_table, item_id, tags)
    conn.commit()
    conn.close()
    return item_id


def _update_item(table: str, tag_table: str, item_id: str, title: str, value: str, tags: str) -> None:
    conn = sqlite3.connect(str(quick_access_db_path()))
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE {table}
        SET title = ?, value = ?
        WHERE ssid = ?
        """,
        (title.strip(), value.strip(), item_id),
    )
    _replace_tags(cur, tag_table, item_id, tags)
    conn.commit()
    conn.close()


def _delete_item(table: str, tag_table: str, item_id: str) -> None:
    conn = sqlite3.connect(str(quick_access_db_path()))
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {tag_table} WHERE ssid = ?", (item_id,))
    cur.execute(f"DELETE FROM {table} WHERE ssid = ?", (item_id,))
    conn.commit()
    conn.close()


def _bump_use_count(table: str, item_id: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(str(quick_access_db_path()))
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE {table}
        SET last_used_date = ?, use_count = use_count + 1
        WHERE ssid = ?
        """,
        (now, item_id),
    )
    conn.commit()
    conn.close()


def _replace_tags(cur: sqlite3.Cursor, tag_table: str, ssid: str, tags: str) -> None:
    cur.execute(f"DELETE FROM {tag_table} WHERE ssid = ?", (ssid,))
    parts = _split_tags(tags)
    for t in parts:
        cur.execute(f"INSERT INTO {tag_table}(ssid, tag) VALUES (?, ?)", (ssid, t))
        cur.execute(
            "INSERT OR IGNORE INTO quick_access_tags(tag, created_date) VALUES (?, ?)",
            (t, datetime.now().isoformat(timespec="seconds")),
        )


def _split_tags(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    tokens = [t.strip() for t in re.split(r"[,]+", text) if t.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)
    return deduped


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
