from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fluxel.core.app_settings import AppSettings, load_settings, save_settings, settings_ini_path
from fluxel.core.fluxel_db import TASK_DB
from fluxel.core.storage_manager import StorageMoveError, move_database_directory, move_settings_file
from fluxel.paths import database_dir, storage_locator_path


def _create_database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


class StorageManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.local_app_data = Path(self.temp.name) / "local"
        self.env_patch = patch.dict(os.environ, {"LOCALAPPDATA": str(self.local_app_data)}, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_database_and_settings_locations_can_move(self) -> None:
        source = database_dir()
        for name in ("Tasks.db", "QuickAccess.db", "Planning.db"):
            _create_database(source / name, name)

        target = Path(self.temp.name) / "OneDrive" / "Fluxel data"
        moved = move_database_directory(target)

        self.assertEqual(database_dir(), target.resolve())
        self.assertEqual(Path(TASK_DB), target.resolve() / "Tasks.db")
        self.assertTrue(all(path.is_file() for path in moved))
        self.assertFalse(any((source / path.name).exists() for path in moved))
        self.assertTrue(storage_locator_path().is_file())
        connection = sqlite3.connect(target / "Planning.db")
        try:
            self.assertEqual(connection.execute("SELECT value FROM sample").fetchone()[0], "Planning.db")
        finally:
            connection.close()

        save_settings(AppSettings(archive_after_days=21))
        original_ini = settings_ini_path()
        moved_ini = Path(self.temp.name) / "OneDrive" / "Fluxel config" / "settings.ini"
        move_settings_file(moved_ini)
        self.assertEqual(settings_ini_path(), moved_ini.resolve())
        self.assertFalse(original_ini.exists())
        self.assertEqual(load_settings().archive_after_days, 21)
        self.assertEqual(database_dir(), target.resolve())

    def test_corrupt_database_is_not_moved(self) -> None:
        source = database_dir()
        corrupt = source / "Tasks.db"
        corrupt.write_bytes(b"not a sqlite database")
        target = Path(self.temp.name) / "destination"

        with self.assertRaises(StorageMoveError):
            move_database_directory(target)

        self.assertTrue(corrupt.is_file())
        self.assertEqual(database_dir(), source)
        self.assertFalse((target / "Tasks.db").exists())


if __name__ == "__main__":
    unittest.main()
