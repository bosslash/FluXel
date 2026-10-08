from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fluxel.core.dbsync import inspect_sync_target, sync_folder
from fluxel.core.fluxel_db import TASK_DB, ensure_tasks_table
from fluxel.core.gantt_db import ensure_gantt_tables
from fluxel.core.quick_access_db import ensure_quick_access_tables
from fluxel.paths import app_state_dir


class FolderDbSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target = self.base / "OneDrive" / "Fluxel Sync"

    def _activate_device(self, name: str) -> None:
        local = self.base / name
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}, clear=False):
            data = app_state_dir()
            # Prevent development-mode migration from a repository-root Tasks.db.
            sqlite3.connect(data / "Tasks.db").close()
            ensure_tasks_table()
            ensure_quick_access_tables()
            ensure_gantt_tables()
        os.environ["LOCALAPPDATA"] = str(local)

    def _insert_task(self, task_id: str, name: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        connection = sqlite3.connect(TASK_DB)
        try:
            connection.execute(
                """
                INSERT INTO tasks(
                    id, name, description, importance, created_at, update_at,
                    end_date, status, stored_urls
                ) VALUES (?, ?, '', '中', ?, ?, '2026-09-30', 'todo', NULL)
                """,
                (task_id, name, now, now),
            )
            connection.commit()
        finally:
            connection.close()

    def _task_names(self) -> list[str]:
        connection = sqlite3.connect(TASK_DB)
        try:
            return [str(row[0]) for row in connection.execute("SELECT name FROM tasks ORDER BY id")]
        finally:
            connection.close()

    def test_two_devices_exchange_updates_and_deletes(self) -> None:
        self._activate_device("device-a")
        self._insert_task("task-1", "Created on A")
        first = sync_folder(self.target)
        self.assertEqual(first.uploaded, 1)
        self.assertEqual(inspect_sync_target(self.target).active_item_count, 1)

        self._activate_device("device-b")
        pulled = sync_folder(self.target)
        self.assertEqual(pulled.downloaded, 1)
        self.assertEqual(self._task_names(), ["Created on A"])

        connection = sqlite3.connect(TASK_DB)
        connection.execute("UPDATE tasks SET name='Updated on B' WHERE id='task-1'")
        connection.commit()
        connection.close()
        pushed = sync_folder(self.target)
        self.assertEqual(pushed.uploaded, 1)

        self._activate_device("device-a")
        updated = sync_folder(self.target)
        self.assertEqual(updated.downloaded, 1)
        self.assertEqual(self._task_names(), ["Updated on B"])

        connection = sqlite3.connect(TASK_DB)
        connection.execute("DELETE FROM tasks WHERE id='task-1'")
        connection.commit()
        connection.close()
        deleted = sync_folder(self.target)
        self.assertGreaterEqual(deleted.deleted, 1)

        self._activate_device("device-b")
        sync_folder(self.target)
        self.assertEqual(self._task_names(), [])

    def test_new_device_merges_remote_and_local_items(self) -> None:
        self._activate_device("source-device")
        self._insert_task("remote-task", "Remote")
        sync_folder(self.target)

        summary = inspect_sync_target(self.target)
        self.assertTrue(summary.initialized)
        self.assertEqual(summary.active_item_count, 1)

        self._activate_device("new-device")
        self._insert_task("local-task", "Local")
        report = sync_folder(self.target)
        self.assertEqual(report.downloaded, 1)
        self.assertEqual(report.uploaded, 1)
        self.assertEqual(self._task_names(), ["Local", "Remote"])


if __name__ == "__main__":
    unittest.main()
