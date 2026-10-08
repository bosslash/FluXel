"""Application settings persisted in a relocatable INI file."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

from fluxel.paths import settings_file_path

_SECTION_KANBAN = "kanban"
_SECTION_EXPORT = "export"
_SECTION_SYNC = "sync"
_DEFAULT_ARCHIVE_AFTER_DAYS = 7


@dataclass(slots=True)
class AppSettings:
    archive_after_days: int = _DEFAULT_ARCHIVE_AFTER_DAYS
    export_ini_path: str = ""
    export_sql_path: str = ""
    sync_folder: str = ""


def settings_ini_path() -> Path:
    return settings_file_path()


def load_settings() -> AppSettings:
    path = settings_ini_path()
    cfg = configparser.ConfigParser()
    if path.is_file():
        cfg.read(path, encoding="utf-8")
    result = AppSettings()
    result.archive_after_days = _clamp_archive_days(
        _safe_int(cfg.get(_SECTION_KANBAN, "archive_after_days", fallback=str(result.archive_after_days)), result.archive_after_days)
    )
    result.export_ini_path = cfg.get(_SECTION_EXPORT, "ini_path", fallback="")
    result.export_sql_path = cfg.get(_SECTION_EXPORT, "sql_path", fallback="")
    result.sync_folder = cfg.get(_SECTION_SYNC, "folder", fallback="").strip()
    return result


def save_settings(settings: AppSettings) -> None:
    cfg = configparser.ConfigParser()
    cfg[_SECTION_KANBAN] = {"archive_after_days": str(_clamp_archive_days(int(settings.archive_after_days)))}
    cfg[_SECTION_EXPORT] = {
        "ini_path": settings.export_ini_path or "",
        "sql_path": settings.export_sql_path or "",
    }
    cfg[_SECTION_SYNC] = {"folder": settings.sync_folder or ""}
    path = settings_ini_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        cfg.write(handle)


def _safe_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _clamp_archive_days(value: int) -> int:
    return min(max(int(value), 1), 365)
