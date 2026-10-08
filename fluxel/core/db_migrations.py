"""Version-aware database migration entry point executed at application startup."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fluxel.core.fluxel_db import TASK_DB, ensure_tasks_table
from fluxel.core.gantt_db import ensure_gantt_tables, gantt_db_path
from fluxel.core.quick_access_db import (
    ensure_quick_access_tables,
    quick_access_db_path,
)


_log = logging.getLogger(__name__)

# Schema shipped for the 2026-08-01 application release.
SCHEMA_VERSION_2026_08_01 = 20260801


@dataclass(frozen=True, slots=True)
class MigrationResult:
    database: str
    previous_version: int
    current_version: int
    migrated: bool


def _read_user_version(path: Path) -> int:
    if not path.exists():
        return 0
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _write_user_version(path: Path, version: int) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.commit()
    finally:
        conn.close()


def migrate_databases() -> list[MigrationResult]:
    """Inspect all application DBs and upgrade schemas older than this release."""
    tasks_path = Path(TASK_DB)
    specifications: list[tuple[Path, Callable[[], None]]] = [
        (tasks_path, ensure_tasks_table),
        (quick_access_db_path(), ensure_quick_access_tables),
        (gantt_db_path(), ensure_gantt_tables),
    ]
    results: list[MigrationResult] = []
    for path, migrate in specifications:
        previous = _read_user_version(path)
        migrated = previous < SCHEMA_VERSION_2026_08_01
        if migrated:
            migrate()
            _write_user_version(path, SCHEMA_VERSION_2026_08_01)
            current = SCHEMA_VERSION_2026_08_01
            _log.info(
                "Database migrated: %s %s -> %s",
                path.name,
                previous,
                current,
            )
        else:
            current = previous
            if previous > SCHEMA_VERSION_2026_08_01:
                _log.warning(
                    "Database schema is newer than this application: %s (%s)",
                    path.name,
                    previous,
                )
        results.append(
            MigrationResult(
                database=path.name,
                previous_version=previous,
                current_version=current,
                migrated=migrated,
            )
        )
    return results
