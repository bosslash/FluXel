"""Shared calendar-scale helpers for date-based charts."""

from __future__ import annotations

from datetime import date


SCALE_MODES = ("day", "month", "quarter", "year")
EXTENSION_DAYS = {
    "day": 366,
    "month": 365 * 4,
    "quarter": 365 * 8,
    "year": 365 * 24,
}
APPROXIMATE_DAYS_PER_SLOT = {
    "day": 1,
    "month": 31,
    "quarter": 92,
    "year": 366,
}


def period_start(value: date, mode: str) -> date:
    """Return the calendar boundary containing *value* for the scale."""
    if mode == "month":
        return date(value.year, value.month, 1)
    if mode == "quarter":
        month = ((value.month - 1) // 3) * 3 + 1
        return date(value.year, month, 1)
    if mode == "year":
        return date(value.year, 1, 1)
    return value


def next_period(value: date, mode: str) -> date:
    """Return the exclusive end of a calendar period."""
    if mode == "day":
        return date.fromordinal(value.toordinal() + 1)
    if mode == "month":
        return (
            date(value.year + 1, 1, 1)
            if value.month == 12
            else date(value.year, value.month + 1, 1)
        )
    if mode == "quarter":
        return (
            date(value.year + 1, 1, 1)
            if value.month >= 10
            else date(value.year, value.month + 3, 1)
        )
    return date(value.year + 1, 1, 1)


def build_periods(
    start: date, end: date, mode: str, *, include_days: bool = False
) -> list[tuple[date, date]]:
    """Build inclusive-range calendar periods for timeline painting."""
    if mode == "day" and not include_days:
        return []
    periods: list[tuple[date, date]] = []
    current = period_start(start, mode)
    while current <= end:
        following = next_period(current, mode)
        periods.append((current, following))
        current = following
    return periods


def extension_days(mode: str) -> int:
    """Return a useful lazy-loading chunk for the requested scale."""
    return EXTENSION_DAYS[mode]


def approximate_days_per_slot(mode: str) -> int:
    """Return a conservative calendar-day estimate for viewport sizing."""
    return APPROXIMATE_DAYS_PER_SLOT[mode]
