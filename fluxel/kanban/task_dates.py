"""タスク期限の表示・分類（カードと共有）。"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime

_JP_WEEKDAY = ("月", "火", "水", "木", "金", "土", "日")


def format_end_date_jp(end_date: str) -> str:
    s = (end_date or "").strip()
    if not s:
        return ""
    head = s[:10].replace("/", "-")
    try:
        d = datetime.strptime(head, "%Y-%m-%d")
    except ValueError:
        return s
    w = _JP_WEEKDAY[d.weekday()]
    return f"{d.strftime('%Y-%m-%d')} ({w})"


def parse_end_date_d(end_date: str) -> date_cls | None:
    s = (end_date or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10].replace("/", "-"), "%Y-%m-%d").date()
    except ValueError:
        return None


def end_date_category(end_date: str) -> str:
    d = parse_end_date_d(end_date)
    if d is None:
        return "none"
    t = date_cls.today()
    if d < t:
        return "past"
    if d == t:
        return "today"
    return "future"
