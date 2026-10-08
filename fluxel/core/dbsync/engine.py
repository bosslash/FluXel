from __future__ import annotations

import threading
from pathlib import Path

from .repository import LocalSyncRepository
from .state import SyncRecord, SyncState
from .target import FolderSyncTarget
from .types import SyncItem, SyncReport, TargetSummary


class SyncBusyError(RuntimeError):
    pass


_SYNC_LOCK = threading.Lock()


def inspect_sync_target(folder: Path) -> TargetSummary:
    return FolderSyncTarget(folder).summary()


def sync_folder(folder: Path) -> SyncReport:
    if not _SYNC_LOCK.acquire(blocking=False):
        raise SyncBusyError("A synchronization is already running.")
    try:
        return _sync_folder(Path(folder))
    finally:
        _SYNC_LOCK.release()


def _sync_folder(folder: Path) -> SyncReport:
    target = FolderSyncTarget(folder)
    target.initialize()
    state = SyncState()
    state.bind_target(str(target.root))
    device_id = state.device_id()
    repository = LocalSyncRepository()
    report = SyncReport()

    current = repository.collect_items()
    records = state.records()
    events = sorted(target.iter_events(), key=lambda event: (event.created_at, event.event_id))
    applied_event_ids = state.applied_event_ids()

    for event in events:
        if event.event_id in applied_event_ids:
            continue
        local_item = current.get(event.key)
        local_hash = local_item.hash if local_item is not None else None
        record = records.get(event.key)
        baseline_hash = record.content_hash if record is not None else None
        local_dirty = local_hash != baseline_hash
        remote_matches_local = event.item_hash == local_hash

        if local_dirty and not remote_matches_local:
            state.add_conflict(
                item_key=event.key,
                event_id=event.event_id,
                local_payload=local_item.data if local_item else None,
                remote_payload=event.data,
            )
            report.conflicts += 1
            # Keep the local value. It is uploaded below as a resolution event.
            state.set_record(
                key=event.key,
                kind=event.kind,
                entity_id=event.entity_id,
                content_hash=event.item_hash,
                payload=event.data,
            )
        elif remote_matches_local:
            state.set_record(
                key=event.key,
                kind=event.kind,
                entity_id=event.entity_id,
                content_hash=event.item_hash,
                payload=event.data,
            )
        else:
            repository.apply_event(event)
            if event.operation == "delete":
                current.pop(event.key, None)
                report.deleted += 1
            else:
                current[event.key] = SyncItem(event.kind, event.entity_id, event.data or {})
                report.downloaded += 1
            state.set_record(
                key=event.key,
                kind=event.kind,
                entity_id=event.entity_id,
                content_hash=event.item_hash,
                payload=event.data,
            )
        state.mark_applied(event.event_id)
        applied_event_ids.add(event.event_id)
        records[event.key] = SyncRecord(
            event.key, event.kind, event.entity_id, event.item_hash, event.data
        )

    current = repository.collect_items()
    records = state.records()
    for key, item in sorted(current.items()):
        record = records.get(key)
        baseline_hash = record.content_hash if record is not None else None
        if item.hash == baseline_hash:
            continue
        event = target.write_event(
            device_id=device_id,
            kind=item.kind,
            entity_id=item.entity_id,
            operation="upsert",
            base_hash=baseline_hash,
            data=item.data,
        )
        state.set_record(
            key=key,
            kind=item.kind,
            entity_id=item.entity_id,
            content_hash=item.hash,
            payload=item.data,
        )
        state.mark_applied(event.event_id)
        report.uploaded += 1

    current_keys = set(current)
    for key, record in sorted(state.records().items()):
        if key in current_keys or record.content_hash is None:
            continue
        event = target.write_event(
            device_id=device_id,
            kind=record.kind,
            entity_id=record.entity_id,
            operation="delete",
            base_hash=record.content_hash,
            data=None,
        )
        state.set_record(
            key=key,
            kind=record.kind,
            entity_id=record.entity_id,
            content_hash=None,
            payload=None,
        )
        state.mark_applied(event.event_id)
        report.uploaded += 1
        report.deleted += 1

    return report
