from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(data: dict[str, Any] | None) -> str | None:
    if data is None:
        return None
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SyncItem:
    kind: str
    entity_id: str
    data: dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.entity_id}"

    @property
    def hash(self) -> str:
        return content_hash(self.data) or ""


@dataclass(frozen=True, slots=True)
class SyncEvent:
    event_id: str
    device_id: str
    kind: str
    entity_id: str
    operation: str
    created_at: str
    base_hash: str | None
    item_hash: str | None
    data: dict[str, Any] | None

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.entity_id}"


@dataclass(slots=True)
class SyncReport:
    downloaded: int = 0
    uploaded: int = 0
    deleted: int = 0
    conflicts: int = 0
    skipped: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.downloaded or self.uploaded or self.deleted)


@dataclass(frozen=True, slots=True)
class TargetSummary:
    folder: str
    initialized: bool
    event_count: int
    active_item_count: int
    device_count: int
