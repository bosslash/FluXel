from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .target import FolderSyncTarget, SyncTargetError


@dataclass(frozen=True, slots=True)
class OneDriveCandidate:
    onedrive_root: Path
    sync_folder: Path
    initialized: bool
    event_count: int


def discover_onedrive_candidates() -> list[OneDriveCandidate]:
    roots: list[Path] = []
    for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        raw = os.environ.get(name)
        if raw:
            roots.append(Path(raw))
    home = Path.home()
    roots.extend(home.glob("OneDrive*"))

    unique: dict[str, Path] = {}
    for root in roots:
        candidate = root.expanduser().resolve(strict=False)
        if candidate.is_dir():
            unique[str(candidate).casefold()] = candidate

    results: list[OneDriveCandidate] = []
    for root in unique.values():
        sync_folder = root / "Fluxel Sync"
        target = FolderSyncTarget(sync_folder)
        initialized = target.is_initialized()
        try:
            event_count = target.summary().event_count if initialized else 0
        except SyncTargetError:
            event_count = 0
        results.append(OneDriveCandidate(root, sync_folder, initialized, event_count))
    return sorted(results, key=lambda item: (not item.initialized, -item.event_count, str(item.onedrive_root)))
