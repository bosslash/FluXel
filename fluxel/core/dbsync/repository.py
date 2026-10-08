from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fluxel.core.fluxel_db import TASK_DB, ensure_tasks_table
from fluxel.core.gantt_db import ensure_gantt_tables, gantt_db_path
from fluxel.core.quick_access_db import ensure_quick_access_tables, quick_access_db_path

from .types import SyncEvent, SyncItem


class LocalSyncRepository:
    """Maps the three application databases to stable logical sync items."""

    def collect_items(self) -> dict[str, SyncItem]:
        ensure_tasks_table()
        ensure_quick_access_tables()
        ensure_gantt_tables()
        items: dict[str, SyncItem] = {}
        for item in self._collect_tasks():
            items[item.key] = item
        for item in self._collect_quick_access():
            items[item.key] = item
        for item in self._collect_gantt():
            items[item.key] = item
        return items

    def apply_event(self, event: SyncEvent) -> None:
        if event.operation == "delete":
            self._delete(event.kind, event.entity_id)
            return
        if event.data is None:
            raise ValueError(f"Missing payload for {event.key}")
        handlers = {
            "task": self._upsert_task,
            "shortcut": lambda data: self._upsert_quick_item(
                "shortcut_phrases", "shortcut_phrase_tags", data
            ),
            "openfile": lambda data: self._upsert_quick_item(
                "openfile_entries", "openfile_entry_tags", data
            ),
            "tag": self._upsert_tag,
            "gantt_project": self._upsert_gantt_project,
            "gantt_term": self._upsert_gantt_term,
        }
        handlers[event.kind](event.data)

    def _collect_tasks(self) -> list[SyncItem]:
        connection = sqlite3.connect(TASK_DB)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT * FROM tasks ORDER BY id").fetchall()
            return [SyncItem("task", str(row["id"]), dict(row)) for row in rows]
        finally:
            connection.close()

    def _collect_quick_access(self) -> list[SyncItem]:
        connection = sqlite3.connect(quick_access_db_path())
        connection.row_factory = sqlite3.Row
        try:
            result: list[SyncItem] = []
            for kind, table, tag_table in (
                ("shortcut", "shortcut_phrases", "shortcut_phrase_tags"),
                ("openfile", "openfile_entries", "openfile_entry_tags"),
            ):
                rows = connection.execute(f"SELECT * FROM {table} ORDER BY ssid").fetchall()
                for row in rows:
                    data = dict(row)
                    data["tags"] = [
                        str(tag_row[0])
                        for tag_row in connection.execute(
                            f"SELECT tag FROM {tag_table} WHERE ssid=? ORDER BY lower(tag), tag",
                            (row["ssid"],),
                        ).fetchall()
                    ]
                    result.append(SyncItem(kind, str(row["ssid"]), data))
            tags = connection.execute(
                "SELECT tag, created_date FROM quick_access_tags ORDER BY lower(tag), tag"
            ).fetchall()
            for row in tags:
                result.append(SyncItem("tag", str(row["tag"]), dict(row)))
            return result
        finally:
            connection.close()

    def _collect_gantt(self) -> list[SyncItem]:
        connection = sqlite3.connect(gantt_db_path())
        connection.row_factory = sqlite3.Row
        try:
            projects = [
                SyncItem("gantt_project", str(row["id"]), dict(row))
                for row in connection.execute(
                    "SELECT * FROM gantt_projects ORDER BY id"
                ).fetchall()
            ]
            terms = [
                SyncItem("gantt_term", str(row["id"]), dict(row))
                for row in connection.execute("SELECT * FROM gantt_terms ORDER BY id").fetchall()
            ]
            return projects + terms
        finally:
            connection.close()

    def _upsert_task(self, data: dict[str, Any]) -> None:
        connection = sqlite3.connect(TASK_DB)
        try:
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            selected = [name for name in data if name in columns]
            if "id" not in selected:
                raise ValueError("Task sync payload has no id")
            updates = [name for name in selected if name != "id"]
            sql = (
                f"INSERT INTO tasks({', '.join(selected)}) VALUES ({', '.join('?' for _ in selected)}) "
                f"ON CONFLICT(id) DO UPDATE SET {', '.join(f'{name}=excluded.{name}' for name in updates)}"
            )
            connection.execute(sql, tuple(data[name] for name in selected))
            connection.commit()
        finally:
            connection.close()

    def _upsert_quick_item(self, table: str, tag_table: str, data: dict[str, Any]) -> None:
        connection = sqlite3.connect(quick_access_db_path())
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                f"""
                INSERT INTO {table}(ssid, title, value, use_count, created_date, last_used_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ssid) DO UPDATE SET
                    title=excluded.title,
                    value=excluded.value,
                    use_count=excluded.use_count,
                    created_date=excluded.created_date,
                    last_used_date=excluded.last_used_date
                """,
                (
                    str(data["ssid"]),
                    str(data.get("title", "")),
                    str(data.get("value", "")),
                    int(data.get("use_count", 0)),
                    str(data.get("created_date", "")),
                    str(data.get("last_used_date", "")),
                ),
            )
            connection.execute(f"DELETE FROM {tag_table} WHERE ssid=?", (str(data["ssid"]),))
            for tag in data.get("tags", []):
                tag_text = str(tag).strip()
                if not tag_text:
                    continue
                connection.execute(
                    f"INSERT INTO {tag_table}(ssid, tag) VALUES (?, ?)",
                    (str(data["ssid"]), tag_text),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO quick_access_tags(tag, created_date) VALUES (?, ?)",
                    (tag_text, str(data.get("created_date", ""))),
                )
            connection.commit()
        finally:
            connection.close()

    def _upsert_tag(self, data: dict[str, Any]) -> None:
        connection = sqlite3.connect(quick_access_db_path())
        try:
            connection.execute(
                """
                INSERT INTO quick_access_tags(tag, created_date) VALUES (?, ?)
                ON CONFLICT(tag) DO UPDATE SET created_date=excluded.created_date
                """,
                (str(data["tag"]), str(data.get("created_date", ""))),
            )
            connection.commit()
        finally:
            connection.close()

    def _upsert_gantt_project(self, data: dict[str, Any]) -> None:
        connection = sqlite3.connect(gantt_db_path())
        try:
            connection.execute(
                """
                INSERT INTO gantt_projects(
                    id, title, description, is_completed, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    is_completed=excluded.is_completed,
                    sort_order=excluded.sort_order,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at
                """,
                tuple(
                    data.get(name)
                    for name in (
                        "id", "title", "description", "is_completed", "sort_order", "created_at", "updated_at"
                    )
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _upsert_gantt_term(self, data: dict[str, Any]) -> None:
        connection = sqlite3.connect(gantt_db_path())
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO gantt_terms(
                    id, project_id, title, description, start_date, end_date,
                    color, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id=excluded.project_id,
                    title=excluded.title,
                    description=excluded.description,
                    start_date=excluded.start_date,
                    end_date=excluded.end_date,
                    color=excluded.color,
                    sort_order=excluded.sort_order,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at
                """,
                tuple(
                    data.get(name)
                    for name in (
                        "id", "project_id", "title", "description", "start_date", "end_date",
                        "color", "sort_order", "created_at", "updated_at"
                    )
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _delete(self, kind: str, entity_id: str) -> None:
        if kind == "task":
            self._execute_delete(Path(TASK_DB), "DELETE FROM tasks WHERE id=?", entity_id)
        elif kind in {"shortcut", "openfile"}:
            table, tag_table = (
                ("shortcut_phrases", "shortcut_phrase_tags")
                if kind == "shortcut"
                else ("openfile_entries", "openfile_entry_tags")
            )
            connection = sqlite3.connect(quick_access_db_path())
            try:
                connection.execute(f"DELETE FROM {tag_table} WHERE ssid=?", (entity_id,))
                connection.execute(f"DELETE FROM {table} WHERE ssid=?", (entity_id,))
                connection.commit()
            finally:
                connection.close()
        elif kind == "tag":
            connection = sqlite3.connect(quick_access_db_path())
            try:
                connection.execute("DELETE FROM quick_access_tags WHERE tag=?", (entity_id,))
                connection.execute("DELETE FROM shortcut_phrase_tags WHERE tag=?", (entity_id,))
                connection.execute("DELETE FROM openfile_entry_tags WHERE tag=?", (entity_id,))
                connection.commit()
            finally:
                connection.close()
        elif kind == "gantt_project":
            self._execute_delete(gantt_db_path(), "DELETE FROM gantt_projects WHERE id=?", entity_id, foreign_keys=True)
        elif kind == "gantt_term":
            self._execute_delete(gantt_db_path(), "DELETE FROM gantt_terms WHERE id=?", entity_id)

    @staticmethod
    def _execute_delete(path: Path, sql: str, entity_id: str, *, foreign_keys: bool = False) -> None:
        connection = sqlite3.connect(path)
        try:
            if foreign_keys:
                connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(sql, (entity_id,))
            connection.commit()
        finally:
            connection.close()
