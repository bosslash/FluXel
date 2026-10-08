"""Dashboard向けのタスク集計。UIから独立した純粋なデータ層。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Collection

from fluxel.core.fluxel_db import TASK_DB


IMPORTANCE_ORDER = ("high", "medium", "low", "unknown")
IMPORTANCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "unknown": "未設定",
}
DEFAULT_STATUSES = ("todo", "doing", "wait")


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    importance_counts: dict[str, int]
    deadline_counts: dict[date, dict[str, int]]
    remaining_total: int
    overdue_total: int
    due_in_7_days: int


def normalize_importance(value: str | None) -> str:
    key = (value or "").strip().lower()
    if key in {"高", "high"}:
        return "high"
    if key in {"中", "medium", "middle"}:
        return "medium"
    if key in {"低", "low"}:
        return "low"
    return "unknown"


def load_dashboard_snapshot(
    db_path: str = TASK_DB,
    *,
    today: date | None = None,
    statuses: Collection[str] | None = None,
) -> DashboardSnapshot:
    """選択されたステータスを集計する。未指定時は未完了3状態。"""
    today = today or date.today()
    selected = tuple(
        dict.fromkeys(
            (status or "").strip().lower()
            for status in (statuses if statuses is not None else DEFAULT_STATUSES)
            if (status or "").strip()
        )
    )
    importance_counts = {key: 0 for key in IMPORTANCE_ORDER}
    deadline_counts: dict[date, dict[str, int]] = {}
    remaining_total = 0
    overdue_total = 0
    due_in_7_days = 0
    if not selected:
        return DashboardSnapshot(
            importance_counts,
            deadline_counts,
            remaining_total,
            overdue_total,
            due_in_7_days,
        )

    placeholders = ",".join("?" for _ in selected)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT importance, end_date
            FROM tasks
            WHERE lower(trim(COALESCE(status, ''))) IN ({placeholders})
            """,
            selected,
        ).fetchall()
    finally:
        conn.close()

    for importance_raw, end_date_raw in rows:
        importance = normalize_importance(importance_raw)
        importance_counts[importance] += 1
        remaining_total += 1
        due_date = _parse_date(end_date_raw)
        if due_date is None:
            continue
        bucket = deadline_counts.setdefault(
            due_date, {key: 0 for key in IMPORTANCE_ORDER}
        )
        bucket[importance] += 1
        if due_date < today:
            overdue_total += 1
        if today <= due_date <= today + timedelta(days=7):
            due_in_7_days += 1

    return DashboardSnapshot(
        importance_counts=importance_counts,
        deadline_counts=dict(sorted(deadline_counts.items())),
        remaining_total=remaining_total,
        overdue_total=overdue_total,
        due_in_7_days=due_in_7_days,
    )


def _parse_date(value: str | None) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10].replace("/", "-"))
    except ValueError:
        return None
