from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fluxel.core import quick_access_db


class QuickAccessDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "QuickAccess.db"
        self.path_patch = patch.object(
            quick_access_db, "quick_access_db_path", return_value=self.db_path
        )
        self.path_patch.start()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_migrates_legacy_value_and_searches_path(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE shortcut_phrases (
                ssid TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_date TEXT NOT NULL,
                last_used_date TEXT NOT NULL
            );
            CREATE TABLE shortcut_phrase_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ssid TEXT NOT NULL,
                tag TEXT NOT NULL
            );
            CREATE TABLE openfile_entries (
                ssid TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_date TEXT NOT NULL,
                last_used_date TEXT NOT NULL
            );
            CREATE TABLE openfile_entry_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ssid TEXT NOT NULL,
                tag TEXT NOT NULL
            );
            CREATE TABLE quick_access_tags (
                tag TEXT PRIMARY KEY,
                created_date TEXT NOT NULL
            );
            INSERT INTO openfile_entries
                (ssid, title, created_date, last_used_date)
            VALUES
                ('C:\\work\\budget.xlsx', '月次資料', '2026-01-01', '2026-01-01');
            """
        )
        conn.commit()
        conn.close()

        quick_access_db.ensure_quick_access_tables()

        rows = quick_access_db.search_openfile_items("budget")
        self.assertEqual(1, len(rows))
        self.assertEqual(r"C:\work\budget.xlsx", rows[0][2])

    def test_searches_multiple_terms_across_title_value_and_tags(self) -> None:
        quick_access_db.ensure_quick_access_tables()
        item_id = quick_access_db.add_openfile_item(
            "月次レポート", r"C:\Finance\budget.xlsx", "経理, 定例"
        )

        rows = quick_access_db.search_openfile_items("月次 budget", "経理")

        self.assertEqual([item_id], [row[0] for row in rows])

    def test_duplicate_values_are_independent_and_usage_is_ranked(self) -> None:
        quick_access_db.ensure_quick_access_tables()
        first = quick_access_db.add_shortcut_item(
            "定型文A", "ありがとうございます", "返信"
        )
        second = quick_access_db.add_shortcut_item(
            "定型文B", "ありがとうございます", "返信"
        )
        self.assertNotEqual(first, second)

        quick_access_db.bump_shortcut_use_count(second)
        rows = quick_access_db.search_shortcut_items("")

        self.assertEqual(second, rows[0][0])
        self.assertEqual(1, rows[0][4])

    def test_like_wildcards_are_literal(self) -> None:
        quick_access_db.ensure_quick_access_tables()
        quick_access_db.add_shortcut_item("100% 完了", "done", "")
        quick_access_db.add_shortcut_item("1000 完了", "other", "")

        rows = quick_access_db.search_shortcut_items("100%")

        self.assertEqual(["100% 完了"], [row[1] for row in rows])


if __name__ == "__main__":
    unittest.main()
