"""Runtime paths for bundled resources and movable user data."""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path

from fluxel.__about__ import APP_VENDOR_DIR


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def bundle_root() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def app_state_dir() -> Path:
    """Return the fixed bootstrap directory that is never relocated."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / APP_VENDOR_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def storage_locator_path() -> Path:
    return app_state_dir() / "location.ini"


def _locator_value(key: str) -> str:
    locator = storage_locator_path()
    if not locator.is_file():
        return ""
    cfg = configparser.ConfigParser()
    try:
        cfg.read(locator, encoding="utf-8")
        return cfg.get("storage", key, fallback="").strip()
    except (OSError, configparser.Error):
        return ""


def _configured_path(raw: str) -> Path | None:
    if not raw:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    return path if path.is_absolute() else None


def database_dir() -> Path:
    """Resolve the current SQLite directory on every call."""
    path = _configured_path(_locator_value("database_dir")) or app_state_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_app_data_dir() -> Path:
    """Backward-compatible alias for the current database directory."""
    return database_dir()


def settings_file_path() -> Path:
    """Resolve the current application INI path on every call."""
    return _configured_path(_locator_value("settings_file")) or (app_state_dir() / "settings.ini")


def task_db_path() -> Path:
    return database_dir() / "Tasks.db"


def app_icon_path() -> Path | None:
    path = bundle_root() / "fig" / "ico" / "app.ico"
    return path if path.is_file() else None
