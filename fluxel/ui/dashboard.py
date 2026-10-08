"""A compact operations dashboard for task workload and deadlines."""

from __future__ import annotations

import math
from datetime import date, timedelta

from PySide6.QtCore import QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from fluxel.core.dashboard_data import (
    IMPORTANCE_ORDER,
    DashboardSnapshot,
    load_dashboard_snapshot,
)
from fluxel.ui.timeline import (
    SCALE_MODES as TIMELINE_SCALE_MODES,
    approximate_days_per_slot,
    build_periods,
    extension_days,
)


BG = QColor("#15171B")
SURFACE = QColor("#1B1E23")
SURFACE_ALT = QColor("#20242A")
BORDER = QColor("#343A43")
GRID = QColor("#303640")
TEXT = QColor("#E5E8EB")
MUTED = QColor("#98A1AC")
COLORS = {
    "high": QColor("#D55C63"),
    "medium": QColor("#D1A24B"),
    "low": QColor("#4D8EAE"),
    "unknown": QColor("#707A86"),
}
IMPORTANCE_TEXT = {
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "unknown": "UNSET",
}
STATUS_LABELS = {
    "todo": "TO DO",
    "doing": "IN PROGRESS",
    "wait": "ON HOLD",
    "finish": "FINISHED",
    "archive": "ARCHIVED",
}


def _panel(painter: QPainter, rect) -> None:
    painter.fillRect(rect, SURFACE)
    painter.setPen(QPen(BORDER, 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(rect.adjusted(0, 0, -1, -1))


class ImportanceDonutChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._counts = {key: 0 for key in IMPORTANCE_ORDER}
        self.setFixedWidth(276)
        self.setFixedHeight(254)

    def set_counts(self, counts: dict[str, int]) -> None:
        self._counts = {
            key: int(counts.get(key, 0)) for key in IMPORTANCE_ORDER
        }
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _panel(painter, self.rect())
        painter.fillRect(0, 0, self.width(), 34, SURFACE_ALT)
        painter.setPen(TEXT)
        painter.setFont(
            QFont(self.font().family(), 9, QFont.Weight.DemiBold)
        )
        painter.drawText(13, 22, "TASK PRIORITY")
        total = sum(self._counts.values())
        pie = QRectF(22, 58, 122, 122)
        if total:
            start = 90 * 16
            for key in IMPORTANCE_ORDER:
                count = self._counts[key]
                if not count:
                    continue
                span = -round((count / total) * 360 * 16)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(COLORS[key])
                painter.drawPie(pie, start, span)
                start += span
            painter.setBrush(SURFACE)
            painter.drawEllipse(pie.adjusted(27, 27, -27, -27))
        else:
            painter.setPen(QPen(BORDER, 14))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(pie.adjusted(8, 8, -8, -8))
        painter.setPen(TEXT)
        painter.setFont(
            QFont(self.font().family(), 16, QFont.Weight.DemiBold)
        )
        painter.drawText(pie, Qt.AlignmentFlag.AlignCenter, str(total))

        painter.setFont(QFont(self.font().family(), 8))
        legend_x, legend_y = 166, 70
        for key in IMPORTANCE_ORDER:
            painter.fillRect(
                QRectF(legend_x, legend_y - 7, 7, 7), COLORS[key]
            )
            painter.setPen(MUTED)
            painter.drawText(
                legend_x + 13,
                legend_y,
                f"{IMPORTANCE_TEXT[key]}  {self._counts[key]}",
            )
            legend_y += 29


class DeadlineStackedBarChart(QWidget):
    SLOT_WIDTH = 30
    MIN_DAY_WIDTH = 18
    MAX_DAY_WIDTH = 66
    ZOOM_STEP = 4
    SCALE_MODES = TIMELINE_SCALE_MODES
    SCALE_WIDTHS = {
        "month": 84,
        "quarter": 116,
        "year": 148,
    }
    LEFT = 44

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: dict[date, dict[str, int]] = {}
        self._today = date.today()
        self._start = self._today - timedelta(days=30)
        self._end = self._today + timedelta(days=120)
        self._scale_mode = "day"
        self._day_width = self.SLOT_WIDTH
        self.setFixedHeight(211)
        self._update_minimum_size()

    @property
    def scale_mode(self) -> str:
        return self._scale_mode

    @property
    def timeline_start(self) -> date:
        return self._start

    @property
    def timeline_end(self) -> date:
        return self._end

    def set_data(self, data: dict[date, dict[str, int]]) -> None:
        self._data = dict(sorted(data.items()))
        required_start = self._today - timedelta(days=30)
        required_end = self._today + timedelta(days=120)
        if data:
            required_start = min(required_start, min(data))
            required_end = max(required_end, max(data))
        self._start = min(self._start, required_start)
        self._end = max(self._end, required_end)
        self._update_minimum_size()
        self.updateGeometry()
        self.update()

    def _periods(self) -> list[tuple[date, date]]:
        return build_periods(
            self._start,
            self._end,
            self._scale_mode,
            include_days=True,
        )

    def _slot_width(self) -> int:
        if self._scale_mode == "day":
            return self._day_width
        return self.SCALE_WIDTHS[self._scale_mode]

    def _timeline_width(self) -> int:
        return len(self._periods()) * self._slot_width()

    def _update_minimum_size(self) -> None:
        width = max(840, 60 + self._timeline_width())
        self.setMinimumWidth(width)
        self.resize(width, self.height())

    def x_for_date(self, value: date) -> int:
        if self._scale_mode == "day":
            return self.LEFT + (value - self._start).days * self._day_width
        width = self._slot_width()
        periods = self._periods()
        for index, (period_start, period_end) in enumerate(periods):
            if value < period_end or index == len(periods) - 1:
                span = max(1, (period_end - period_start).days)
                fraction = (value - period_start).days / span
                return round(self.LEFT + (index + fraction) * width)
        return self.LEFT + len(periods) * width

    def date_for_x(self, x: float) -> date:
        if self._scale_mode == "day":
            index = round((float(x) - self.LEFT) / self._day_width)
            index = max(0, min((self._end - self._start).days, index))
            return self._start + timedelta(days=index)
        periods = self._periods()
        width = self._slot_width()
        position = max(0.0, float(x) - self.LEFT)
        index = max(0, min(len(periods) - 1, int(position // width)))
        period_start, period_end = periods[index]
        fraction = max(0.0, min(1.0, (position - index * width) / width))
        days = (period_end - period_start).days
        value = period_start + timedelta(days=round(fraction * days))
        return max(self._start, min(self._end, value))

    def extend_timeline(
        self, *, before_days: int = 0, after_days: int = 0
    ) -> int:
        before_days = max(0, int(before_days))
        after_days = max(0, int(after_days))
        if before_days == 0 and after_days == 0:
            return 0
        anchor = self._start
        old_anchor_x = self.x_for_date(anchor)
        if before_days:
            self._start -= timedelta(days=before_days)
        if after_days:
            self._end += timedelta(days=after_days)
        self._update_minimum_size()
        self.updateGeometry()
        self.update()
        return self.x_for_date(anchor) - old_anchor_x

    def ensure_scrollable_span(self, viewport_width: int) -> None:
        required_width = max(840, int(viewport_width) + 320)
        current_width = self._timeline_width()
        if current_width >= required_width:
            return
        missing_slots = (
            math.ceil((required_width - current_width) / self._slot_width())
            + 2
        )
        days_per_slot = approximate_days_per_slot(self._scale_mode)
        missing_days = missing_slots * days_per_slot
        before_days = missing_days // 2
        self.extend_timeline(
            before_days=before_days,
            after_days=missing_days - before_days,
        )

    def set_day_width(self, width: int) -> bool:
        if self._scale_mode != "day":
            return False
        value = max(self.MIN_DAY_WIDTH, min(self.MAX_DAY_WIDTH, int(width)))
        if value == self._day_width:
            return False
        self._day_width = value
        self._update_minimum_size()
        self.updateGeometry()
        self.update()
        return True

    def change_zoom(self, direction: int) -> bool:
        if self._scale_mode == "day":
            if direction > 0:
                return self.set_day_width(self._day_width + self.ZOOM_STEP)
            if self._day_width > self.MIN_DAY_WIDTH:
                return self.set_day_width(self._day_width - self.ZOOM_STEP)
            self._scale_mode = "month"
        else:
            index = self.SCALE_MODES.index(self._scale_mode)
            target = index - 1 if direction > 0 else index + 1
            if not 0 <= target < len(self.SCALE_MODES):
                return False
            self._scale_mode = self.SCALE_MODES[target]
            if self._scale_mode == "day":
                self._day_width = self.MIN_DAY_WIDTH
        self._update_minimum_size()
        self.updateGeometry()
        self.update()
        return True

    def sizeHint(self) -> QSize:
        return QSize(max(840, self.minimumWidth()), 211)

    def _period_values(
        self, period_start: date, period_end: date
    ) -> dict[str, int]:
        totals = {key: 0 for key in IMPORTANCE_ORDER}
        for due_date, values in self._data.items():
            if period_start <= due_date < period_end:
                for key in IMPORTANCE_ORDER:
                    totals[key] += int(values.get(key, 0))
        return totals

    def _period_label(self, period_start: date) -> str:
        if self._scale_mode == "day":
            return period_start.strftime("%m/%d")
        if self._scale_mode == "month":
            return period_start.strftime("%b %Y").upper()
        if self._scale_mode == "quarter":
            quarter = ((period_start.month - 1) // 3) + 1
            return f"Q{quarter} {period_start.year}"
        return str(period_start.year)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), SURFACE)
        painter.setFont(QFont(self.font().family(), 8))
        left, top, bottom = self.LEFT, 13, self.height() - 29
        chart_h = max(bottom - top, 80)
        periods = self._periods()
        period_values = [
            self._period_values(period_start, period_end)
            for period_start, period_end in periods
        ]
        max_total = max(
            [sum(values.values()) for values in period_values] or [1]
        )
        step = max(1, math.ceil(max_total / 3))
        grid_max = max(step, math.ceil(max_total / step) * step)
        for value in range(0, grid_max + 1, step):
            y = bottom - (value / grid_max) * chart_h
            painter.setPen(QPen(GRID, 1))
            painter.drawLine(left, int(y), self.width() - 12, int(y))
            painter.setPen(MUTED)
            painter.drawText(13, int(y + 3), str(value))

        slot_width = self._slot_width()
        for index, ((period_start, period_end), values) in enumerate(
            zip(periods, period_values)
        ):
            x = left + index * slot_width
            if self._scale_mode == "day" and period_start.weekday() >= 5:
                painter.fillRect(
                    QRectF(x, top, slot_width, chart_h),
                    QColor(255, 255, 255, 5),
                )
            if period_start <= self._today < period_end:
                painter.fillRect(
                    QRectF(x, top, slot_width, chart_h),
                    QColor(78, 137, 177, 25),
                )
                painter.setPen(QPen(QColor("#4E89B1"), 1))
                painter.drawLine(x, top, x, bottom)
            current_y = float(bottom)
            bar_width = max(8.0, min(28.0, slot_width * 0.36))
            bar_x = x + (slot_width - bar_width) / 2
            for key in ("low", "medium", "high", "unknown"):
                count = values.get(key, 0)
                if not count:
                    continue
                height = max(2.0, (count / grid_max) * chart_h)
                current_y -= height
                painter.fillRect(
                    QRectF(bar_x, current_y, bar_width, height),
                    COLORS[key],
                )
            show_label = self._scale_mode != "day" or (
                period_start.day == 1
                or period_start.weekday() == 0
                or period_start == self._today
            )
            if show_label:
                painter.setPen(
                    TEXT if period_start <= self._today < period_end else MUTED
                )
                painter.drawText(
                    QRectF(x, bottom + 2, slot_width, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    self._period_label(period_start),
                )


class DeadlineScrollArea(QScrollArea):
    zoom_requested = Signal(int, int)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_requested.emit(
                    1 if delta > 0 else -1,
                    int(event.position().x()),
                )
            event.accept()
            return
        super().wheelEvent(event)


class MetricStrip(QFrame):
    def __init__(
        self, title: str, state_color: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setStyleSheet(
            "QFrame { background:#1B1E23; border:1px solid #343A43; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 5, 12, 5)
        dot = QFrame(self)
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(
            f"QFrame {{ background:{state_color}; border:none; "
            "border-radius:3px; }"
        )
        label = QLabel(title, self)
        label.setStyleSheet(
            "QLabel { color:#98A1AC; font-size:9px; "
            "font-weight:600; border:none; }"
        )
        self.value = QLabel("0", self)
        self.value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.value.setStyleSheet(
            "QLabel { color:#F0F2F4; font-size:18px; "
            "font-weight:600; border:none; }"
        )
        layout.addWidget(dot)
        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(self.value)


PAGE_STYLE = """
DashboardPage { background:#15171B; color:#E5E8EB; }
QPushButton {
    color:#DDE2E7; background:#24282F; border:1px solid #3A414B;
    border-radius:3px; padding:4px 10px; min-height:22px;
}
QPushButton:hover { background:#2C323A; border-color:#596575; }
QPushButton:pressed { background:#20242A; }
"""


class DashboardPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(PAGE_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 11, 14, 14)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("OPERATIONS OVERVIEW", self)
        title.setStyleSheet(
            "QLabel { color:#F1F3F5; font-size:15px; font-weight:700; "
            "letter-spacing:1px; }"
        )
        subtitle = QLabel("TASK WORKLOAD AND DEADLINE HEALTH", self)
        subtitle.setStyleSheet(
            "QLabel { color:#7F8995; font-size:8px; letter-spacing:1px; }"
        )
        self._btn_prev = QPushButton("‹ 4 weeks", self)
        self._btn_today = QPushButton("Today", self)
        self._btn_next = QPushButton("4 weeks ›", self)
        refresh = QPushButton("Refresh", self)
        self._btn_prev.clicked.connect(lambda: self._shift_deadline(-28))
        self._btn_today.clicked.connect(self._scroll_deadline_to_today)
        self._btn_next.clicked.connect(lambda: self._shift_deadline(28))
        refresh.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch(1)
        header.addWidget(self._btn_prev)
        header.addWidget(self._btn_today)
        header.addWidget(self._btn_next)
        header.addSpacing(5)
        header.addWidget(refresh)
        root.addLayout(header)

        filter_frame = QFrame(self)
        filter_frame.setStyleSheet(
            "QFrame { background:#1B1E23; border:1px solid #343A43; }"
        )
        filters = QHBoxLayout(filter_frame)
        filters.setContentsMargins(9, 5, 9, 5)
        filters.setSpacing(5)
        filter_label = QLabel("DISPLAY", filter_frame)
        filter_label.setStyleSheet(
            "QLabel { color:#89939F; font-size:8px; font-weight:600; "
            "border:none; }"
        )
        filters.addWidget(filter_label)
        self._status_buttons: dict[str, QPushButton] = {}
        for status, label in STATUS_LABELS.items():
            button = QPushButton(label, filter_frame)
            button.setCheckable(True)
            button.setChecked(status in {"todo", "doing", "wait"})
            button.setStyleSheet(
                "QPushButton { color:#AAB2BC; background:#20242A; "
                "border:1px solid #363D47; border-radius:2px; "
                "padding:2px 9px; min-height:18px; font-size:8px; }"
                "QPushButton:checked { color:#FFFFFF; background:#28445B; "
                "border-color:#4C86B3; }"
            )
            button.toggled.connect(self.refresh)
            filters.addWidget(button)
            self._status_buttons[status] = button
        filters.addStretch(1)
        self._filter_summary = QLabel("", filter_frame)
        self._filter_summary.setStyleSheet(
            "QLabel { color:#89939F; font-size:8px; border:none; }"
        )
        filters.addWidget(self._filter_summary)
        root.addWidget(filter_frame)

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self._remaining = MetricStrip("TASKS IN SCOPE", "#4E89B1", self)
        self._overdue = MetricStrip("OVERDUE", "#D55C63", self)
        self._week = MetricStrip("DUE IN 7 DAYS", "#D1A24B", self)
        metrics.addWidget(self._remaining)
        metrics.addWidget(self._overdue)
        metrics.addWidget(self._week)
        root.addLayout(metrics)

        self._donut = ImportanceDonutChart(self)
        self._deadline = DeadlineStackedBarChart(self)
        self._deadline_scroll = DeadlineScrollArea(self)
        self._deadline_scroll.setWidgetResizable(False)
        self._deadline_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._deadline_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._deadline_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._deadline_scroll.setFixedHeight(220)
        self._deadline_scroll.viewport().setStyleSheet("background:#15171B;")
        self._deadline_scroll.horizontalScrollBar().setStyleSheet(
            "QScrollBar:horizontal { background:#111317; height:9px; }"
            "QScrollBar::handle:horizontal { background:#47515E; "
            "min-width:44px; border-radius:4px; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal "
            "{ width:0; border:none; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal "
            "{ background:transparent; }"
        )
        self._deadline_scroll.setWidget(self._deadline)
        self._extending_deadline = False
        self._deadline_scroll.horizontalScrollBar().valueChanged.connect(
            self._on_deadline_scroll_changed
        )
        self._deadline_scroll.zoom_requested.connect(self._zoom_deadline)
        self._deadline_zoom_in = QShortcut(
            QKeySequence("Ctrl++"), self._deadline_scroll
        )
        self._deadline_zoom_in_equal = QShortcut(
            QKeySequence("Ctrl+="), self._deadline_scroll
        )
        self._deadline_zoom_out = QShortcut(
            QKeySequence("Ctrl+-"), self._deadline_scroll
        )
        for shortcut in (
            self._deadline_zoom_in,
            self._deadline_zoom_in_equal,
            self._deadline_zoom_out,
        ):
            shortcut.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
        self._deadline_zoom_in.activated.connect(
            lambda: self._zoom_deadline(1)
        )
        self._deadline_zoom_in_equal.activated.connect(
            lambda: self._zoom_deadline(1)
        )
        self._deadline_zoom_out.activated.connect(
            lambda: self._zoom_deadline(-1)
        )

        self._deadline_panel = QFrame(self)
        self._deadline_panel.setFixedHeight(254)
        self._deadline_panel.setStyleSheet(
            "QFrame#deadlinePanel { background:#1B1E23; "
            "border:1px solid #343A43; }"
        )
        self._deadline_panel.setObjectName("deadlinePanel")
        deadline_layout = QVBoxLayout(self._deadline_panel)
        deadline_layout.setContentsMargins(1, 1, 1, 1)
        deadline_layout.setSpacing(0)
        deadline_header = QFrame(self._deadline_panel)
        deadline_header.setFixedHeight(32)
        deadline_header.setStyleSheet(
            "QFrame { background:#20242A; border:none; "
            "border-bottom:1px solid #343A43; }"
        )
        deadline_header_layout = QHBoxLayout(deadline_header)
        deadline_header_layout.setContentsMargins(12, 0, 12, 0)
        deadline_header_layout.setSpacing(14)
        deadline_title = QLabel("DEADLINE WORKLOAD", deadline_header)
        deadline_title.setStyleSheet(
            "QLabel { color:#E5E8EB; font-size:9px; "
            "font-weight:600; border:none; }"
        )
        deadline_header_layout.addWidget(deadline_title)
        self._deadline_scale = QLabel("DAY", deadline_header)
        self._deadline_scale.setStyleSheet(
            "QLabel { color:#7FAFD0; font-size:8px; font-weight:600; "
            "border:none; }"
        )
        deadline_header_layout.addWidget(self._deadline_scale)
        zoom_out = QPushButton("−", deadline_header)
        zoom_in = QPushButton("+", deadline_header)
        for button in (zoom_out, zoom_in):
            button.setFixedSize(24, 20)
            button.setStyleSheet(
                "QPushButton { padding:0; min-height:18px; "
                "font-size:11px; }"
            )
        zoom_out.clicked.connect(lambda: self._zoom_deadline(-1))
        zoom_in.clicked.connect(lambda: self._zoom_deadline(1))
        deadline_header_layout.addWidget(zoom_out)
        deadline_header_layout.addWidget(zoom_in)
        deadline_header_layout.addStretch(1)
        for key in ("high", "medium", "low", "unknown"):
            legend = QLabel(f"■  {IMPORTANCE_TEXT[key]}", deadline_header)
            legend.setStyleSheet(
                f"QLabel {{ color:{COLORS[key].name()}; "
                "font-size:8px; border:none; }"
            )
            deadline_header_layout.addWidget(legend)
        deadline_layout.addWidget(deadline_header)
        deadline_layout.addWidget(self._deadline_scroll)

        charts = QHBoxLayout()
        charts.setSpacing(8)
        charts.addWidget(self._donut)
        charts.addWidget(self._deadline_panel, 1)
        root.addLayout(charts)
        root.addStretch(1)
        self._did_initial_scroll = False
        self.refresh()

    def selected_statuses(self) -> set[str]:
        return {
            status
            for status, button in self._status_buttons.items()
            if button.isChecked()
        }

    def refresh(self) -> DashboardSnapshot:
        statuses = self.selected_statuses()
        snapshot = load_dashboard_snapshot(statuses=statuses)
        self._remaining.value.setText(str(snapshot.remaining_total))
        self._overdue.value.setText(str(snapshot.overdue_total))
        self._week.value.setText(str(snapshot.due_in_7_days))
        self._filter_summary.setText(
            f"{len(statuses)} STATES  ·  {snapshot.remaining_total} TASKS"
        )
        self._donut.set_counts(snapshot.importance_counts)
        self._deadline.set_data(snapshot.deadline_counts)
        if not self._did_initial_scroll:
            self._did_initial_scroll = True
            QTimer.singleShot(0, self._scroll_deadline_to_today)
        return snapshot

    def _deadline_extension_days(self) -> int:
        return extension_days(self._deadline.scale_mode)

    def _on_deadline_scroll_changed(self, value: int) -> None:
        if self._extending_deadline:
            return
        bar = self._deadline_scroll.horizontalScrollBar()
        maximum = bar.maximum()
        if maximum <= 0:
            return
        threshold = max(160, min(800, bar.pageStep() // 2))
        extend_before = value <= threshold
        extend_after = maximum - value <= threshold
        if not extend_before and not extend_after:
            return
        chunk = self._deadline_extension_days()
        self._extending_deadline = True
        try:
            prepend_shift = self._deadline.extend_timeline(
                before_days=chunk if extend_before else 0,
                after_days=chunk if extend_after else 0,
            )
            if prepend_shift:
                bar.setValue(value + prepend_shift)
        finally:
            self._extending_deadline = False

    def _ensure_deadline_date(self, target: date) -> None:
        chunk = self._deadline_extension_days()
        before_days = 0
        after_days = 0
        if target < self._deadline.timeline_start:
            before_days = max(
                chunk, (self._deadline.timeline_start - target).days + 28
            )
        if target > self._deadline.timeline_end:
            after_days = max(
                chunk, (target - self._deadline.timeline_end).days + 28
            )
        if before_days or after_days:
            self._deadline.extend_timeline(
                before_days=before_days, after_days=after_days
            )

    def _zoom_deadline(
        self, direction: int, viewport_x: int | None = None
    ) -> bool:
        viewport_width = self._deadline_scroll.viewport().width()
        if viewport_x is None:
            viewport_x = viewport_width // 2
        bar = self._deadline_scroll.horizontalScrollBar()
        anchor_date = self._deadline.date_for_x(bar.value() + viewport_x)
        self._extending_deadline = True
        try:
            if not self._deadline.change_zoom(direction):
                return False
            self._deadline.ensure_scrollable_span(viewport_width)
            bar.setValue(
                self._deadline.x_for_date(anchor_date) - viewport_x
            )
        finally:
            self._extending_deadline = False
        self._deadline_scale.setText(
            self._deadline.scale_mode.upper()
        )
        return True

    def _scroll_deadline_to_today(self) -> None:
        self._ensure_deadline_date(date.today())
        x = self._deadline.x_for_date(date.today())
        bar = self._deadline_scroll.horizontalScrollBar()
        bar.setValue(
            max(0, x - self._deadline_scroll.viewport().width() // 3)
        )

    def _shift_deadline(self, days: int) -> None:
        bar = self._deadline_scroll.horizontalScrollBar()
        anchor_x = max(1, self._deadline_scroll.viewport().width() // 3)
        visible_date = self._deadline.date_for_x(bar.value() + anchor_x)
        target = visible_date + timedelta(days=int(days))
        self._ensure_deadline_date(target)
        bar.setValue(self._deadline.x_for_date(target) - anchor_x)
