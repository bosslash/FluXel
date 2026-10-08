"""Kanbanから独立したGantt用SQLiteデータ層。"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from fluxel.paths import local_app_data_dir


@dataclass(frozen=True, slots=True)
class GanttProject:
    id: str
    title: str
    description: str
    is_completed: bool
    sort_order: int


@dataclass(frozen=True, slots=True)
class GanttTerm:
    id: str
    project_id: str
    title: str
    description: str
    start_date: date
    end_date: date
    color: str
    sort_order: int


def gantt_db_path() -> Path:
    return local_app_data_dir() / "Planning.db"


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_gantt_tables(db_path: Path | None = None) -> None:
    """テーブル作成と、既存DBに対する非破壊の列追加を行う。"""
    path = db_path or gantt_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS gantt_projects (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                is_completed INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS gantt_terms (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#2E7BD9',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES gantt_projects(id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_gantt_terms_project
                ON gantt_terms(project_id, sort_order, start_date);
            """
        )
        project_columns = _column_names(conn, "gantt_projects")
        if "description" not in project_columns:
            conn.execute(
                "ALTER TABLE gantt_projects "
                "ADD COLUMN description TEXT NOT NULL DEFAULT ''"
            )
        if "is_completed" not in project_columns:
            conn.execute(
                "ALTER TABLE gantt_projects "
                "ADD COLUMN is_completed INTEGER NOT NULL DEFAULT 0"
            )
        term_columns = _column_names(conn, "gantt_terms")
        if "description" not in term_columns:
            conn.execute(
                "ALTER TABLE gantt_terms "
                "ADD COLUMN description TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()
    finally:
        conn.close()


def list_projects(
    db_path: Path | None = None, *, include_completed: bool = True
) -> list[GanttProject]:
    path = db_path or gantt_db_path()
    ensure_gantt_tables(path)
    conn = sqlite3.connect(path)
    try:
        where = "" if include_completed else "WHERE is_completed = 0"
        rows = conn.execute(
            f"""
            SELECT id, title, description, is_completed, sort_order
            FROM gantt_projects
            {where}
            ORDER BY sort_order, lower(title), id
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        GanttProject(
            id=str(row[0]),
            title=str(row[1]),
            description=str(row[2] or ""),
            is_completed=bool(row[3]),
            sort_order=int(row[4]),
        )
        for row in rows
    ]


def list_terms(db_path: Path | None = None) -> list[GanttTerm]:
    path = db_path or gantt_db_path()
    ensure_gantt_tables(path)
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            """
            SELECT id, project_id, title, description, start_date, end_date,
                   color, sort_order
            FROM gantt_terms
            ORDER BY project_id, sort_order, start_date, lower(title), id
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        GanttTerm(
            id=str(row[0]),
            project_id=str(row[1]),
            title=str(row[2]),
            description=str(row[3] or ""),
            start_date=date.fromisoformat(str(row[4])),
            end_date=date.fromisoformat(str(row[5])),
            color=str(row[6] or "#2E7BD9"),
            sort_order=int(row[7]),
        )
        for row in rows
    ]


def add_project(
    title: str,
    db_path: Path | None = None,
    *,
    description: str = "",
    is_completed: bool = False,
) -> str:
    path = db_path or gantt_db_path()
    ensure_gantt_tables(path)
    project_id = str(uuid.uuid7())
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(path)
    try:
        next_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM gantt_projects"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO gantt_projects
                (id, title, description, is_completed, sort_order,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                title.strip(),
                description.strip(),
                int(is_completed),
                int(next_order),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return project_id


def update_project(
    project_id: str,
    title: str,
    description: str,
    is_completed: bool,
    db_path: Path | None = None,
) -> None:
    path = db_path or gantt_db_path()
    ensure_gantt_tables(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            UPDATE gantt_projects
            SET title=?, description=?, is_completed=?, updated_at=?
            WHERE id=?
            """,
            (
                title.strip(),
                description.strip(),
                int(is_completed),
                datetime.now().isoformat(timespec="seconds"),
                project_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def rename_project(
    project_id: str, title: str, db_path: Path | None = None
) -> None:
    path = db_path or gantt_db_path()
    ensure_gantt_tables(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "UPDATE gantt_projects SET title=?, updated_at=? WHERE id=?",
            (title.strip(), datetime.now().isoformat(timespec="seconds"), project_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_project(project_id: str, db_path: Path | None = None) -> None:
    path = db_path or gantt_db_path()
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM gantt_projects WHERE id=?", (project_id,))
        conn.commit()
    finally:
        conn.close()


def add_term(
    project_id: str,
    title: str,
    start_date: date,
    end_date: date,
    *,
    description: str = "",
    color: str = "#2E7BD9",
    db_path: Path | None = None,
) -> str:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    path = db_path or gantt_db_path()
    ensure_gantt_tables(path)
    term_id = str(uuid.uuid7())
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(path)
    try:
        next_order = conn.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1
            FROM gantt_terms WHERE project_id=?
            """,
            (project_id,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO gantt_terms
                (id, project_id, title, description, start_date, end_date,
                 color, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                term_id,
                project_id,
                title.strip(),
                description.strip(),
                start_date.isoformat(),
                end_date.isoformat(),
                color,
                int(next_order),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return term_id


def update_term(
    term_id: str,
    project_id: str,
    title: str,
    start_date: date,
    end_date: date,
    *,
    description: str | None = None,
    color: str = "#2E7BD9",
    db_path: Path | None = None,
) -> None:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    path = db_path or gantt_db_path()
    ensure_gantt_tables(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            UPDATE gantt_terms
            SET project_id=?, title=?, description=COALESCE(?, description),
                start_date=?, end_date=?, color=?, updated_at=?
            WHERE id=?
            """,
            (
                project_id,
                title.strip(),
                None if description is None else description.strip(),
                start_date.isoformat(),
                end_date.isoformat(),
                color,
                datetime.now().isoformat(timespec="seconds"),
                term_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def move_term_days(
    term_id: str, days: int, db_path: Path | None = None
) -> tuple[date, date]:
    path = db_path or gantt_db_path()
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT start_date, end_date FROM gantt_terms WHERE id=?", (term_id,)
        ).fetchone()
        if row is None:
            raise KeyError(term_id)
        start = date.fromisoformat(str(row[0])) + timedelta(days=int(days))
        end = date.fromisoformat(str(row[1])) + timedelta(days=int(days))
        conn.execute(
            """
            UPDATE gantt_terms
            SET start_date=?, end_date=?, updated_at=?
            WHERE id=?
            """,
            (
                start.isoformat(),
                end.isoformat(),
                datetime.now().isoformat(timespec="seconds"),
                term_id,
            ),
        )
        conn.commit()
        return start, end
    finally:
        conn.close()


def reorder_term(
    term_id: str, direction: int, db_path: Path | None = None
) -> bool:
    """同一Project内でTermを1行だけ並べ替える。"""
    path = db_path or gantt_db_path()
    ensure_gantt_tables(path)
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT project_id FROM gantt_terms WHERE id=?", (term_id,)
        ).fetchone()
        if row is None:
            return False
        project_id = str(row[0])
        ids = [
            str(item[0])
            for item in conn.execute(
                """
                SELECT id FROM gantt_terms
                WHERE project_id=?
                ORDER BY sort_order, start_date, lower(title), id
                """,
                (project_id,),
            )
        ]
        index = ids.index(term_id)
        target = index + (-1 if direction < 0 else 1)
        if not 0 <= target < len(ids):
            return False
        ids[index], ids[target] = ids[target], ids[index]
        now = datetime.now().isoformat(timespec="seconds")
        conn.executemany(
            "UPDATE gantt_terms SET sort_order=?, updated_at=? WHERE id=?",
            [(order, now, item_id) for order, item_id in enumerate(ids)],
        )
        conn.commit()
        return True
    finally:
        conn.close()


def move_term_to_project(
    term_id: str,
    target_project_id: str,
    db_path: Path | None = None,
) -> bool:
    """Termの内容を保持したまま別Projectの末尾へ移動する。"""
    path = db_path or gantt_db_path()
    ensure_gantt_tables(path)
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT project_id FROM gantt_terms WHERE id=?", (term_id,)
        ).fetchone()
        if row is None or str(row[0]) == target_project_id:
            return False
        exists = conn.execute(
            "SELECT 1 FROM gantt_projects WHERE id=?", (target_project_id,)
        ).fetchone()
        if exists is None:
            return False
        next_order = conn.execute(
            """
            SELECT COALESCE(MAX(sort_order), -1) + 1
            FROM gantt_terms WHERE project_id=?
            """,
            (target_project_id,),
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE gantt_terms
            SET project_id=?, sort_order=?, updated_at=?
            WHERE id=?
            """,
            (
                target_project_id,
                int(next_order),
                datetime.now().isoformat(timespec="seconds"),
                term_id,
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_term(term_id: str, db_path: Path | None = None) -> None:
    path = db_path or gantt_db_path()
    conn = sqlite3.connect(path)
    try:
        conn.execute("DELETE FROM gantt_terms WHERE id=?", (term_id,))
        conn.commit()
    finally:
        conn.close()
