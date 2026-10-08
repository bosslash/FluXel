from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fluxel.ui import task_search


class TaskSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "Tasks.db"
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                importance TEXT,
                created_at TEXT NOT NULL,
                update_at TEXT NOT NULL,
                end_date TEXT,
                status TEXT NOT NULL,
                stored_urls TEXT
            );
            INSERT INTO tasks VALUES
                ('1', '請求書を確認', '7月分の金額を照合する', 'high',
                 '2026-01-01', '2026-01-01', '2026-07-31', 'todo', ''),
                ('2', '月次作業', '請求書の送付を完了する', 'normal',
                 '2026-01-01', '2026-01-01', '2026-07-30', 'doing', ''),
                ('3', '過去の請求書', '7月分', 'normal',
                 '2026-01-01', '2026-01-01', '2026-06-30', 'archive', '');
            """
        )
        conn.commit()
        conn.close()
        self.db_patch = patch.object(task_search, "TASK_DB", str(self.db_path))
        self.db_patch.start()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_multiple_terms_can_span_title_and_body(self) -> None:
        title_rows, body_rows = task_search.fetch_search_results(
            "月次 請求書", include_archive=False
        )

        self.assertEqual([], title_rows)
        self.assertEqual(["2"], [row[0] for row in body_rows])

    def test_archive_filter(self) -> None:
        without_archive = task_search.fetch_search_results(
            "過去", include_archive=False
        )
        with_archive = task_search.fetch_search_results(
            "過去", include_archive=True
        )

        self.assertEqual(([], []), without_archive)
        self.assertEqual(["3"], [row[0] for row in with_archive[0]])


if __name__ == "__main__":
    unittest.main()
