from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fluxel.ui import task_search


class TaskSearchFilterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "Tasks.db"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
                importance TEXT, created_at TEXT NOT NULL, update_at TEXT NOT NULL,
                end_date TEXT, status TEXT NOT NULL, stored_urls TEXT
            );
            INSERT INTO tasks VALUES
                ('1', 'Critical review', 'OneDrive sync', '高', 'x', 'x', '2026-09-01', 'doing', ''),
                ('2', 'Normal review', 'OneDrive sync', '中', 'x', 'x', '2026-09-02', 'todo', ''),
                ('3', 'Archived review', 'OneDrive sync', '低', 'x', 'x', '2026-09-03', 'archive', '');
            """
        )
        connection.commit()
        connection.close()
        self.db_patch = patch.object(task_search, "TASK_DB", str(self.database))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_status_and_importance_filters(self) -> None:
        title, body = task_search.fetch_search_results(
            "review", include_archive=False, status_filter="doing", importance_filter="high"
        )
        self.assertEqual(["1"], [row[0] for row in title + body])

    def test_filter_only_search_and_explicit_archive(self) -> None:
        title, body = task_search.fetch_search_results(
            "", include_archive=False, status_filter="archive"
        )
        self.assertEqual(["3"], [row[0] for row in title + body])


if __name__ == "__main__":
    unittest.main()
