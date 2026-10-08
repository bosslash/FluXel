from __future__ import annotations

import unittest
from datetime import date

from fluxel.ui.timeline import (
    approximate_days_per_slot,
    build_periods,
    extension_days,
    next_period,
    period_start,
)


class TimelineTest(unittest.TestCase):
    def test_calendar_boundaries(self) -> None:
        value = date(2026, 8, 17)
        self.assertEqual(date(2026, 8, 1), period_start(value, "month"))
        self.assertEqual(date(2026, 7, 1), period_start(value, "quarter"))
        self.assertEqual(date(2026, 1, 1), period_start(value, "year"))
        self.assertEqual(date(2027, 1, 1), next_period(date(2026, 12, 1), "month"))
        self.assertEqual(date(2027, 1, 1), next_period(date(2026, 10, 1), "quarter"))

    def test_builds_each_scale(self) -> None:
        start = date(2026, 1, 15)
        end = date(2026, 4, 2)
        self.assertEqual([], build_periods(start, end, "day"))
        self.assertEqual(
            78, len(build_periods(start, end, "day", include_days=True))
        )
        self.assertEqual(4, len(build_periods(start, end, "month")))
        self.assertEqual(2, len(build_periods(start, end, "quarter")))
        self.assertEqual(1, len(build_periods(start, end, "year")))

    def test_scale_loading_constants_are_complete(self) -> None:
        for mode in ("day", "month", "quarter", "year"):
            self.assertGreater(extension_days(mode), 0)
            self.assertGreater(approximate_days_per_slot(mode), 0)


if __name__ == "__main__":
    unittest.main()
