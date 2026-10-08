"""Validated, recoverable relocation of Fluxel storage files."""

from __future__ import annotations

import configparser
import os
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

from fluxel.paths import database_dir, settings_file_path, storage_locator_path

DATABASE_FILENAMES = ("Tasks.db", "QuickAccess.db", "Planning.db")
SQLITE_SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")


class StorageMoveError(RuntimeError):
    pass


def is_onedrive_path(path: Path) -> bool:
    resolved = str(path.resolve(strict=False)).casefold()
    roots = (os.environ.get("OneDrive"), os.environ.get("OneDriveConsumer"), os.environ.get("OneDriveCommercial"))
    for root in roots:
        if root:
            parent = str(Path(root).resolve(strict=False)).casefold().rstrip("\\/")
            if resolved == parent or resolved.startswith(parent + os.sep.casefold()):
                return True
    return "\\onedrive" in resolved or "/onedrive" in resolved


def database_paths(directory: Path | None = None) -> tuple[Path, ...]:
    root = directory or database_dir()
    return tuple(root / name for name in DATABASE_FILENAMES)


def move_database_directory(target_directory: Path) -> tuple[Path, ...]:
    source_directory = database_dir().resolve(strict=False)
    target_directory = Path(target_directory).expanduser().resolve(strict=False)
    if source_directory == target_directory:
        return database_paths(target_directory)
    _prepare_directory(target_directory)
    sources = [path for path in database_paths(source_directory) if path.is_file()]
    collisions = [target_directory / path.name for path in sources if (target_directory / path.name).exists()]
    if collisions:
        raise StorageMoveError("The destination already contains: " + ", ".join(path.name for path in collisions))

    staged: list[tuple[Path, Path, Path]] = []
    try:
        for source in sources:
            _validate_sqlite(source)
            destination = target_directory / source.name
            temporary = target_directory / f".{source.name}.{uuid.uuid4().hex}.moving"
            shutil.copy2(source, temporary)
            _validate_sqlite(temporary)
            staged.append((source, temporary, destination))
        for _source, temporary, destination in staged:
            os.replace(temporary, destination)
        write_storage_locator(database_directory=target_directory)
    except Exception as exc:
        for _source, temporary, _destination in staged:
            temporary.unlink(missing_ok=True)
        if isinstance(exc, StorageMoveError):
            raise
        raise StorageMoveError(f"Database move failed. The original files were kept.\n{exc}") from exc

    for source, _temporary, _destination in staged:
        source.unlink(missing_ok=True)
        for suffix in SQLITE_SIDECAR_SUFFIXES:
            Path(str(source) + suffix).unlink(missing_ok=True)
    return database_paths(target_directory)


def move_settings_file(target_file: Path) -> Path:
    source = settings_file_path().resolve(strict=False)
    target = Path(target_file).expanduser().resolve(strict=False)
    if source == target:
        return target
    _prepare_directory(target.parent)
    if target.exists():
        raise StorageMoveError(f"The destination already contains {target.name}.")
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.moving"
    try:
        shutil.copy2(source, temporary) if source.is_file() else temporary.write_text("", encoding="utf-8")
        cfg = configparser.ConfigParser()
        cfg.read(temporary, encoding="utf-8")
        os.replace(temporary, target)
        write_storage_locator(settings_file=target)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, StorageMoveError):
            raise
        raise StorageMoveError(f"Settings move failed. The original file was kept.\n{exc}") from exc
    source.unlink(missing_ok=True)
    return target


def write_storage_locator(*, database_directory: Path | None = None, settings_file: Path | None = None) -> None:
    locator = storage_locator_path()
    cfg = configparser.ConfigParser()
    if locator.is_file():
        try:
            cfg.read(locator, encoding="utf-8")
        except configparser.Error as exc:
            raise StorageMoveError(f"Cannot read storage locator: {exc}") from exc
    if not cfg.has_section("storage"):
        cfg.add_section("storage")
    if database_directory is not None:
        cfg.set("storage", "database_dir", str(Path(database_directory).resolve(strict=False)))
    if settings_file is not None:
        cfg.set("storage", "settings_file", str(Path(settings_file).resolve(strict=False)))
    locator.parent.mkdir(parents=True, exist_ok=True)
    temporary = locator.with_name(f".{locator.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            cfg.write(handle)
        os.replace(temporary, locator)
    finally:
        temporary.unlink(missing_ok=True)


def find_uninstaller() -> Path | None:
    if getattr(sys, "frozen", False):
        candidates = sorted(Path(sys.executable).resolve().parent.glob("unins*.exe"))
        return candidates[0] if candidates else None
    return None


def _prepare_directory(directory: Path) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".fluxel-write-test-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise StorageMoveError(f"The destination is not writable.\n{directory}\n{exc}") from exc


def _validate_sqlite(path: Path) -> None:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path)
        mode = connection.execute("PRAGMA journal_mode").fetchone()
        if mode and str(mode[0]).casefold() == "wal":
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        result = connection.execute("PRAGMA quick_check").fetchone()
        if not result or str(result[0]).casefold() != "ok":
            raise StorageMoveError(f"SQLite validation failed for {path.name}: {result}")
    except sqlite3.Error as exc:
        raise StorageMoveError(f"SQLite validation failed for {path.name}: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()
