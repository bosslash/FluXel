"""SQLite DB パスと tasks テーブル初期化。"""

import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fluxel.paths import is_frozen, task_db_path

# 配布時は %LOCALAPPDATA%\\Fluxel\\Tasks.db（開発時も同じルール）
class _DynamicTaskDbPath(os.PathLike[str]):
    """Keep legacy TASK_DB imports valid after the storage location changes."""

    def __fspath__(self) -> str:
        return str(task_db_path())

    def __str__(self) -> str:
        return str(task_db_path())


TASK_DB = _DynamicTaskDbPath()


def _migrate_fluxeel_appdata_db_if_needed() -> None:
    """旧名 FluXel フォルダにだけ DB がある場合、%LOCALAPPDATA%\\Fluxel\\ へ一度だけコピー。"""
    dest = Path(TASK_DB)
    if dest.exists():
        return
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return
    old = Path(base) / "FluXel" / "Tasks.db"
    if old.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, dest)


def _migrate_legacy_cwd_db_if_needed() -> None:
    """未配布時のみ、カレントの Tasks.db を新パスへ一度だけ移す。"""
    if is_frozen():
        return
    dest = Path(TASK_DB)
    if dest.exists():
        return
    legacy = Path.cwd() / "Tasks.db"
    if legacy.is_file():
        shutil.copy2(legacy, dest)


def ensure_tasks_table() -> None:
    """tasks テーブルを指定スキーマで作成する。"""
    _migrate_fluxeel_appdata_db_if_needed()
    _migrate_legacy_cwd_db_if_needed()
    conn = sqlite3.connect(TASK_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            importance TEXT,
            created_at TEXT NOT NULL,
            update_at TEXT NOT NULL,
            end_date TEXT,
            status TEXT NOT NULL,
            stored_urls TEXT
        )
        """
    )
    cursor.execute("PRAGMA table_info(tasks)")
    columns = {row[1] for row in cursor.fetchall()}
    if "importance" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN importance TEXT")
    if "stored_urls" not in columns:
        cursor.execute("ALTER TABLE tasks ADD COLUMN stored_urls TEXT")
    conn.commit()
    conn.close()


def auto_archive_stale_finish_tasks(*, days: int = 7) -> None:
    """Finish のまま最終更新から指定日数を超えたタスクを archive に移す（update_at を更新）。"""
    cutoff = (datetime.now() - timedelta(days=max(int(days), 1))).isoformat(timespec="seconds")
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(TASK_DB)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE tasks
        SET status = 'archive', update_at = ?
        WHERE lower(trim(status)) = 'finish' AND update_at < ?
        """,
        (now, cutoff),
    )
    conn.commit()
    conn.close()
