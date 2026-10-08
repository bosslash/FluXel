from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from fluxel.paths import app_state_dir

from .target import utc_now


@dataclass(frozen=True, slots=True)
class SyncRecord:
    key: str
    kind: str
    entity_id: str
    content_hash: str | None
    payload: dict | None


class SyncState:
    """Device-local synchronization metadata. This database is never synchronized."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_state_dir() / "SyncState.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def ensure_schema(self) -> None:
        connection = self.connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sync_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_records (
                    item_key TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    content_hash TEXT,
                    payload TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS applied_events (
                    event_id TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_key TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    local_payload TEXT,
                    remote_payload TEXT,
                    detected_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def device_id(self) -> str:
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT value FROM sync_metadata WHERE key='device_id'"
            ).fetchone()
            if row:
                return str(row[0])
            value = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO sync_metadata(key, value) VALUES ('device_id', ?)",
                (value,),
            )
            connection.commit()
            return value
        finally:
            connection.close()

    def bind_target(self, target_key: str) -> None:
        """Reset per-target cursors when the user selects a different folder."""
        normalized = target_key.casefold()
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT value FROM sync_metadata WHERE key='target_key'"
            ).fetchone()
            if row and str(row[0]) == normalized:
                return
            connection.execute("DELETE FROM sync_records")
            connection.execute("DELETE FROM applied_events")
            connection.execute("DELETE FROM sync_conflicts")
            connection.execute(
                """
                INSERT INTO sync_metadata(key, value) VALUES ('target_key', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (normalized,),
            )
            connection.commit()
        finally:
            connection.close()

    def records(self) -> dict[str, SyncRecord]:
        connection = self.connect()
        try:
            rows = connection.execute(
                "SELECT item_key, kind, entity_id, content_hash, payload FROM sync_records"
            ).fetchall()
        finally:
            connection.close()
        result: dict[str, SyncRecord] = {}
        for row in rows:
            payload = json.loads(row[4]) if row[4] else None
            record = SyncRecord(str(row[0]), str(row[1]), str(row[2]), row[3], payload)
            result[record.key] = record
        return result

    def set_record(
        self,
        *,
        key: str,
        kind: str,
        entity_id: str,
        content_hash: str | None,
        payload: dict | None,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload is not None else None
        connection = self.connect()
        try:
            connection.execute(
                """
                INSERT INTO sync_records(item_key, kind, entity_id, content_hash, payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    kind=excluded.kind,
                    entity_id=excluded.entity_id,
                    content_hash=excluded.content_hash,
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (key, kind, entity_id, content_hash, encoded, utc_now()),
            )
            connection.commit()
        finally:
            connection.close()

    def applied_event_ids(self) -> set[str]:
        connection = self.connect()
        try:
            return {
                str(row[0])
                for row in connection.execute("SELECT event_id FROM applied_events").fetchall()
            }
        finally:
            connection.close()

    def is_applied(self, event_id: str) -> bool:
        connection = self.connect()
        try:
            row = connection.execute(
                "SELECT 1 FROM applied_events WHERE event_id=?", (event_id,)
            ).fetchone()
            return row is not None
        finally:
            connection.close()

    def mark_applied(self, event_id: str) -> None:
        connection = self.connect()
        try:
            connection.execute(
                "INSERT OR IGNORE INTO applied_events(event_id, applied_at) VALUES (?, ?)",
                (event_id, utc_now()),
            )
            connection.commit()
        finally:
            connection.close()

    def add_conflict(
        self,
        *,
        item_key: str,
        event_id: str,
        local_payload: dict | None,
        remote_payload: dict | None,
    ) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """
                INSERT OR IGNORE INTO sync_conflicts(
                    item_key, event_id, local_payload, remote_payload, detected_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    item_key,
                    event_id,
                    json.dumps(local_payload, ensure_ascii=False, sort_keys=True) if local_payload is not None else None,
                    json.dumps(remote_payload, ensure_ascii=False, sort_keys=True) if remote_payload is not None else None,
                    utc_now(),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def unresolved_conflict_count(self) -> int:
        connection = self.connect()
        try:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM sync_conflicts WHERE resolved_at IS NULL"
                ).fetchone()[0]
            )
        finally:
            connection.close()
