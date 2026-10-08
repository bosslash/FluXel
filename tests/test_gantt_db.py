from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fluxel.core.gantt_db import (
    add_project,
    add_term,
    delete_project,
    ensure_gantt_tables,
    list_projects,
    list_terms,
    move_term_days,
    move_term_to_project,
    reorder_term,
    update_project,
    update_term,
)


class GanttDbTest(unittest.TestCase):
    def test_project_term_crud_and_move(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "Planning.db"
            ensure_gantt_tables(db_path)
            project_id = add_project(
                "Website renewal",
                db_path,
                description="Public website replacement",
            )
            second_project = add_project("Operations", db_path)
            first_term = add_term(
                project_id,
                "Design",
                date(2026, 8, 1),
                date(2026, 8, 5),
                description="Create UI specifications",
                db_path=db_path,
            )
            second_term = add_term(
                project_id,
                "Build",
                date(2026, 8, 6),
                date(2026, 8, 12),
                db_path=db_path,
            )

            start, end = move_term_days(first_term, 3, db_path)
            self.assertEqual(date(2026, 8, 4), start)
            self.assertEqual(date(2026, 8, 8), end)

            update_term(
                first_term,
                project_id,
                "UI Design",
                start,
                end,
                description="Approved UI specifications",
                color="#E53935",
                db_path=db_path,
            )
            terms = list_terms(db_path)
            self.assertEqual("UI Design", terms[0].title)
            self.assertEqual("Approved UI specifications", terms[0].description)
            self.assertEqual("#E53935", terms[0].color)

            self.assertTrue(reorder_term(second_term, -1, db_path))
            self.assertEqual(second_term, list_terms(db_path)[0].id)
            self.assertTrue(
                move_term_to_project(first_term, second_project, db_path)
            )
            moved = {term.id: term for term in list_terms(db_path)}[first_term]
            self.assertEqual(second_project, moved.project_id)

            update_project(
                project_id,
                "Website renewal",
                "Completed rollout",
                True,
                db_path,
            )
            self.assertTrue(list_projects(db_path)[0].is_completed)
            self.assertEqual(
                [second_project],
                [
                    project.id
                    for project in list_projects(
                        db_path, include_completed=False
                    )
                ],
            )

            delete_project(project_id, db_path)
            self.assertEqual(1, len(list_projects(db_path)))

    def test_migrates_legacy_schema_without_losing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "Planning.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE gantt_projects (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE gantt_terms (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    title TEXT NOT NULL, start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL, color TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                INSERT INTO gantt_projects VALUES
                    ('p1','Legacy',0,'2026-01-01','2026-01-01');
                INSERT INTO gantt_terms VALUES
                    ('t1','p1','Legacy term','2026-08-01','2026-08-02',
                     '#123456',0,'2026-01-01','2026-01-01');
                """
            )
            conn.commit()
            conn.close()

            ensure_gantt_tables(db_path)

            projects = list_projects(db_path)
            terms = list_terms(db_path)
            self.assertEqual("Legacy", projects[0].title)
            self.assertEqual("", projects[0].description)
            self.assertFalse(projects[0].is_completed)
            self.assertEqual("Legacy term", terms[0].title)
            self.assertEqual("", terms[0].description)

    def test_rejects_reverse_date_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "Planning.db"
            project_id = add_project("P", db_path)
            with self.assertRaises(ValueError):
                add_term(
                    project_id,
                    "Invalid",
                    date(2026, 8, 5),
                    date(2026, 8, 1),
                    db_path=db_path,
                )


if __name__ == "__main__":
    unittest.main()
