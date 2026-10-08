"""大量デモタスク投入（FLUXEL_SEED_DEMO=1 または CLI --seed-demo）。"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta

from fluxel.core.fluxel_db import TASK_DB

_DEMO_PREFIX = "demo-seed-"
_TARGET_COUNT = 420


def seed_demo_tasks_if_requested(*, force: bool = False) -> None:
    """
    FLUXEL_SEED_DEMO=1 のとき、demo-seed-* が 200 件未満なら数百件 INSERT。
    force=True のとき既存 demo-seed-* を削除してから再投入。
    """
    env_ok = os.environ.get("FLUXEL_SEED_DEMO", "").strip() == "1"
    if not env_ok and not force:
        return

    conn = sqlite3.connect(TASK_DB)
    cur = conn.cursor()
    if force:
        cur.execute("DELETE FROM tasks WHERE id LIKE ?", (_DEMO_PREFIX + "%",))
        conn.commit()
    else:
        cur.execute(
            "SELECT COUNT(1) FROM tasks WHERE id LIKE ?",
            (_DEMO_PREFIX + "%",),
        )
        (existing,) = cur.fetchone()
        if existing >= 200:
            conn.close()
            return

    base = date(2026, 5, 5)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    week_later = today + timedelta(days=7)
    end_cycle = (
        base.isoformat(),
        today.isoformat(),
        tomorrow.isoformat(),
        week_later.isoformat(),
    )

    statuses = ("todo", "doing", "wait", "finish", "archive")
    imps = ("高", "中", "低")
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[tuple] = []
    for i in range(_TARGET_COUNT):
        tid = f"{_DEMO_PREFIX}{i:05d}"
        st = statuses[i % len(statuses)]
        ed = end_cycle[i % len(end_cycle)]
        imp = imps[i % len(imps)]
        created = (datetime(2026, 5, 4, 8, (i % 60), 0)).isoformat(timespec="seconds")
        name = f"デモ {i:04d} [{st}]"
        desc = (
            f"説明サンプル {i}。基準日2026-05-05系と今日/明日/+7日の期限を混在。"
            f" \\url:https://example.com/demo/{i} 参照。"
        )
        rows.append(
            (tid, name, desc, imp, created, now, ed, st, None),
        )

    cur.executemany(
        """
        INSERT OR REPLACE INTO tasks
        (id, name, description, importance, created_at, update_at, end_date, status, stored_urls)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
