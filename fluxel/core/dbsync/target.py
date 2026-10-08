from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .constants import (
    SUPPORTED_KINDS,
    SYNC_CONTAINER_NAME,
    SYNC_EVENTS_DIR,
    SYNC_FORMAT_VERSION,
    SYNC_INFO_FILE,
    SYNC_VERSION_DIR,
)
from .types import SyncEvent, TargetSummary, canonical_json, content_hash


class SyncTargetError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class FolderSyncTarget:
    """Append-only filesystem target transported by the OneDrive desktop client."""

    def __init__(self, selected_folder: Path) -> None:
        self.selected_folder = Path(selected_folder).expanduser().resolve(strict=False)
        self.root = self.selected_folder / SYNC_CONTAINER_NAME / SYNC_VERSION_DIR

    @property
    def info_path(self) -> Path:
        return self.root / SYNC_INFO_FILE

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / SYNC_EVENTS_DIR).mkdir(parents=True, exist_ok=True)
        if not self.info_path.exists():
            _atomic_json_write(
                self.info_path,
                {
                    "format": "Fluxel folder sync",
                    "format_version": SYNC_FORMAT_VERSION,
                    "created_at": utc_now(),
                },
            )
        self._validate_info()

    def is_initialized(self) -> bool:
        return self.info_path.is_file()

    def iter_events(self) -> Iterator[SyncEvent]:
        events_root = self.root / SYNC_EVENTS_DIR
        if not events_root.is_dir():
            return
        for path in sorted(events_root.rglob("*.json")):
            yield self.read_event(path)

    def read_event(self, path: Path) -> SyncEvent:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if int(raw.get("format_version", 0)) != SYNC_FORMAT_VERSION:
                raise SyncTargetError(f"Unsupported sync event version: {path}")
            kind = str(raw["kind"])
            if kind not in SUPPORTED_KINDS:
                raise SyncTargetError(f"Unsupported sync item type: {kind}")
            data = raw.get("data")
            if data is not None and not isinstance(data, dict):
                raise SyncTargetError(f"Invalid event payload: {path}")
            expected = raw.get("item_hash")
            if expected != content_hash(data):
                raise SyncTargetError(f"Event checksum mismatch: {path}")
            return SyncEvent(
                event_id=str(raw["event_id"]),
                device_id=str(raw["device_id"]),
                kind=kind,
                entity_id=str(raw["entity_id"]),
                operation=str(raw["operation"]),
                created_at=str(raw["created_at"]),
                base_hash=raw.get("base_hash"),
                item_hash=expected,
                data=data,
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SyncTargetError(f"Cannot read sync event {path}: {exc}") from exc

    def write_event(
        self,
        *,
        device_id: str,
        kind: str,
        entity_id: str,
        operation: str,
        base_hash: str | None,
        data: dict | None,
    ) -> SyncEvent:
        self.initialize()
        now = datetime.now(UTC)
        event = SyncEvent(
            event_id=str(uuid.uuid7()),
            device_id=device_id,
            kind=kind,
            entity_id=entity_id,
            operation=operation,
            created_at=now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            base_hash=base_hash,
            item_hash=content_hash(data),
            data=data,
        )
        path = (
            self.root
            / SYNC_EVENTS_DIR
            / kind
            / f"{now.year:04d}"
            / f"{now.month:02d}"
            / f"{event.event_id}_{_safe_component(device_id)}.json"
        )
        _atomic_json_write(
            path,
            {
                "format_version": SYNC_FORMAT_VERSION,
                "event_id": event.event_id,
                "device_id": event.device_id,
                "kind": event.kind,
                "entity_id": event.entity_id,
                "operation": event.operation,
                "created_at": event.created_at,
                "base_hash": event.base_hash,
                "item_hash": event.item_hash,
                "data": event.data,
            },
        )
        return event

    def summary(self) -> TargetSummary:
        initialized = self.is_initialized()
        latest: dict[str, SyncEvent] = {}
        devices: set[str] = set()
        event_count = 0
        if initialized:
            self._validate_info()
            for event in self.iter_events():
                event_count += 1
                devices.add(event.device_id)
                latest[event.key] = event
        active = sum(1 for event in latest.values() if event.operation != "delete")
        return TargetSummary(str(self.selected_folder), initialized, event_count, active, len(devices))

    def _validate_info(self) -> None:
        try:
            raw = json.loads(self.info_path.read_text(encoding="utf-8"))
            version = int(raw.get("format_version", 0))
        except (OSError, ValueError, TypeError) as exc:
            raise SyncTargetError(f"Cannot read sync target metadata: {exc}") from exc
        if version != SYNC_FORMAT_VERSION:
            raise SyncTargetError(
                f"Sync target version {version} is not supported by this version of Fluxel."
            )


def _safe_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value)[:80]


def _atomic_json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.partial")
    encoded = (canonical_json(value) + "\n").encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise SyncTargetError(f"Cannot write to the sync folder: {path}\n{exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
