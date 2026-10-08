from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fluxel.core.dashboard_data import load_dashboard_snapshot


class DashboardDataTest(unittest.TestCase):
    def test_remaining_composition_and_deadlines(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "Tasks.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY, name TEXT, description TEXT,
                    importance TEXT, created_at TEXT, update_at TEXT,
                    end_date TEXT, status TEXT, stored_urls TEXT
                );
                INSERT INTO tasks VALUES
                    ('1','A','','高','','','2026-07-25','todo',''),
                    ('2','B','','中','','','2026-07-28','doing',''),
                    ('3','C','','低','','','2026-07-28','wait',''),
                    ('4','D','','高','','','2026-07-30','finish',''),
                    ('5','E','','高','','','2026-07-31','archive','');
                """
            )
            conn.commit()
            conn.close()

            snapshot = load_dashboard_snapshot(
                str(db_path), today=date(2026, 7, 26)
            )

            self.assertEqual(3, snapshot.remaining_total)
            self.assertEqual(1, snapshot.overdue_total)
            self.assertEqual(2, snapshot.due_in_7_days)
            self.assertEqual({"high": 1, "medium": 1, "low": 1, "unknown": 0},
                             snapshot.importance_counts)
            self.assertEqual(2, sum(snapshot.deadline_counts[date(2026, 7, 28)].values()))


            completed = load_dashboard_snapshot(
                str(db_path),
                today=date(2026, 7, 26),
                statuses={"finish", "archive"},
            )
            self.assertEqual(2, completed.remaining_total)
            self.assertEqual(
                {"high": 2, "medium": 0, "low": 0, "unknown": 0},
                completed.importance_counts,
            )


if __name__ == "__main__":
    unittest.main()
