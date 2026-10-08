"""デモタスク投入用 CLI（`uv run fluxel-seed`）。環境の `python` が使えなくても uv 経由で実行できる。"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

_DEMO_LIKE = "demo-seed-%"


def _count_demo() -> int:
    from fluxel.core.fluxel_db import TASK_DB

    conn = sqlite3.connect(TASK_DB)
    try:
        (n,) = conn.execute(
            "SELECT COUNT(1) FROM tasks WHERE id LIKE ?",
            (_DEMO_LIKE,),
        ).fetchone()
        return int(n)
    finally:
        conn.close()


def _count_all() -> int:
    from fluxel.core.fluxel_db import TASK_DB

    conn = sqlite3.connect(TASK_DB)
    try:
        (n,) = conn.execute("SELECT COUNT(1) FROM tasks").fetchone()
        return int(n)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fluxel のデモタスク（demo-seed-*）を SQLite に投入します。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="既存の demo-seed-* を削除してから再投入します。",
    )
    args = parser.parse_args()

    os.environ["FLUXEL_SEED_DEMO"] = "1"

    from fluxel.core.demo_seed import seed_demo_tasks_if_requested
    from fluxel.core.fluxel_db import TASK_DB, ensure_tasks_table

    ensure_tasks_table()
    before = _count_demo()
    seed_demo_tasks_if_requested(force=args.force)
    demo = _count_demo()
    total = _count_all()

    print(f"DB: {TASK_DB}", file=sys.stderr)
    if args.force:
        print(f"デモ行（demo-seed-*）: {demo} 件（再投入モード）", file=sys.stderr)
    elif before >= 200:
        print(
            "デモは既に 200 件以上あります（スキップ）。"
            "入れ直す場合は: uv run fluxel-seed --force",
            file=sys.stderr,
        )
    else:
        print(f"デモ行（demo-seed-*）: {demo} 件を投入しました。", file=sys.stderr)
    print(f"tasks 合計: {total} 件", file=sys.stderr)


if __name__ == "__main__":
    main()
