"""A compact, keyboard-first Project/Term Gantt view."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from PySide6.QtCore import QDate, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from fluxel.core.gantt_db import (
    GanttProject,
    GanttTerm,
    add_project,
    add_term,
    delete_project,
    delete_term,
    ensure_gantt_tables,
    list_projects,
    list_terms,
    move_term_days,
    move_term_to_project,
    reorder_term,
    update_project,
    update_term,
)
from fluxel.ui.timeline import (
    SCALE_MODES as TIMELINE_SCALE_MODES,
    build_periods,
    extension_days,
    next_period,
    period_start,
)


BG = QColor("#15171B")
SURFACE = QColor("#1B1E23")
LEFT_SURFACE = QColor("#202329")
HEADER = QColor("#252930")
PROJECT_ROW = QColor("#22272E")
SELECTED_ROW = QColor("#27384B")
BORDER = QColor("#353A43")
GRID = QColor("#323740")
TEXT = QColor("#E3E6EA")
MUTED = QColor("#9AA2AD")
TERM_BAR = QColor("#2F78D8")
TERM_BAR_SELECTED = QColor("#3F8BEA")
PROJECT_BAR = QColor("#0EA58F")
TODAY = QColor("#E15353")
MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class GanttCanvas(QWidget):
    term_selected = Signal(str)
    project_selected = Signal(str)
    term_moved = Signal(str, int)
    term_edit_requested = Signal(str)
    project_edit_requested = Signal(str)
    navigation_requested = Signal(int, int)  # direction, action

    ACTION_SELECT_TERM = 0
    ACTION_SELECT_PROJECT = 1
    ACTION_REORDER_TERM = 2
    ACTION_MOVE_TERM_PROJECT = 3

    LEFT = 370
    NAME_WIDTH = 242
    HEADER_HEIGHT = 64
    ROW = 36
    DAY = 34
    MIN_DAY = 18
    MAX_DAY = 74
    ZOOM_STEP = 4
    SCALE_MODES = TIMELINE_SCALE_MODES
    SCALE_WIDTHS = {
        "month": 96,
        "quarter": 144,
        "year": 180,
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._projects: list[GanttProject] = []
        self._terms: list[GanttTerm] = []
        self._rows: list[tuple[str, GanttProject | GanttTerm]] = []
        self._start = date.today() - timedelta(days=28)
        self._end = date.today() + timedelta(days=180)
        self._selected_term_id = ""
        self._selected_project_id = ""
        self._drag_term: GanttTerm | None = None
        self._drag_origin_x = 0.0
        self._drag_delta = 0
        self._horizontal_offset = 0
        self._scale_mode = "day"
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumHeight(320)

    @property
    def selected_term_id(self) -> str:
        return self._selected_term_id

    @property
    def selected_project_id(self) -> str:
        return self._selected_project_id

    @property
    def projects(self) -> list[GanttProject]:
        return list(self._projects)

    @property
    def terms(self) -> list[GanttTerm]:
        return list(self._terms)

    @property
    def timeline_start(self) -> date:
        return self._start

    @property
    def timeline_end(self) -> date:
        return self._end

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

    def selected_term(self) -> GanttTerm | None:
        return next(
            (term for term in self._terms if term.id == self._selected_term_id),
            None,
        )

    def select_project(self, project_id: str) -> bool:
        if not any(project.id == project_id for project in self._projects):
            return False
        self._selected_project_id = project_id
        self._selected_term_id = ""
        self.project_selected.emit(project_id)
        self.update()
        return True

    def select_term(self, term_id: str) -> bool:
        term = next((item for item in self._terms if item.id == term_id), None)
        if term is None:
            return False
        self._selected_term_id = term_id
        self._selected_project_id = term.project_id
        self.term_selected.emit(term_id)
        self.project_selected.emit(term.project_id)
        self.update()
        return True

    def set_rows(
        self, projects: list[GanttProject], terms: list[GanttTerm]
    ) -> None:
        self._projects = projects
        project_ids = {project.id for project in projects}
        self._terms = [term for term in terms if term.project_id in project_ids]
        by_project: dict[str, list[GanttTerm]] = {}
        for term in self._terms:
            by_project.setdefault(term.project_id, []).append(term)
        self._rows = []
        for project in projects:
            self._rows.append(("project", project))
            self._rows.extend(
                ("term", term) for term in by_project.get(project.id, [])
            )
        term_dates = [
            value
            for term in self._terms
            for value in (term.start_date, term.end_date)
        ]
        required_start = min(
            [date.today() - timedelta(days=28), *term_dates]
        )
        required_end = max(
            [date.today() + timedelta(days=180), *term_dates]
        )
        self._start = min(self._start, required_start)
        self._end = max(self._end, required_end)
        self._update_minimum_size()
        if self._selected_term_id and not any(
            term.id == self._selected_term_id for term in self._terms
        ):
            self._selected_term_id = ""
        if self._selected_project_id not in project_ids:
            self._selected_project_id = ""
        self.updateGeometry()
        self.update()

    @property
    def scale_mode(self) -> str:
        return self._scale_mode

    def _period_start(self, value: date, mode: str | None = None) -> date:
        return period_start(value, mode or self._scale_mode)

    @staticmethod
    def _next_period(value: date, mode: str) -> date:
        return next_period(value, mode)

    def _periods(self) -> list[tuple[date, date]]:
        return build_periods(self._start, self._end, self._scale_mode)

    def _timeline_width(self) -> int:
        if self._scale_mode == "day":
            return ((self._end - self._start).days + 1) * self.DAY
        return len(self._periods()) * self.SCALE_WIDTHS[self._scale_mode]

    def _update_minimum_size(self) -> None:
        size = (
            self.LEFT + self._timeline_width(),
            self.HEADER_HEIGHT + max(len(self._rows), 9) * self.ROW + 4,
        )
        self.setMinimumSize(*size)
        self.resize(*size)

    def x_for_date(self, value: date) -> int:
        if self._scale_mode == "day":
            return self.LEFT + (value - self._start).days * self.DAY
        width = self.SCALE_WIDTHS[self._scale_mode]
        periods = self._periods()
        for index, (period_start, period_end) in enumerate(periods):
            if value < period_end or index == len(periods) - 1:
                span = max(1, (period_end - period_start).days)
                fraction = (value - period_start).days / span
                return round(self.LEFT + (index + fraction) * width)
        return self.LEFT + len(periods) * width

    def date_for_x(self, x: float) -> date:
        if self._scale_mode == "day":
            index = round((float(x) - self.LEFT) / self.DAY)
            index = max(0, min((self._end - self._start).days, index))
            return self._start + timedelta(days=index)
        periods = self._periods()
        width = self.SCALE_WIDTHS[self._scale_mode]
        position = max(0.0, float(x) - self.LEFT)
        index = max(0, min(len(periods) - 1, int(position // width)))
        period_start, period_end = periods[index]
        fraction = max(0.0, min(1.0, (position - index * width) / width))
        days = (period_end - period_start).days
        value = period_start + timedelta(days=round(fraction * days))
        return max(self._start, min(self._end, value))

    def set_day_width(self, width: int) -> bool:
        if self._scale_mode != "day":
            return False
        value = max(self.MIN_DAY, min(self.MAX_DAY, int(width)))
        if value == self.DAY:
            return False
        self.DAY = value
        self._update_minimum_size()
        self.updateGeometry()
        self.update()
        return True

    def change_zoom(self, direction: int) -> bool:
        if self._scale_mode == "day":
            if direction > 0:
                return self.set_day_width(self.DAY + self.ZOOM_STEP)
            if self.DAY > self.MIN_DAY:
                return self.set_day_width(self.DAY - self.ZOOM_STEP)
            self._scale_mode = "month"
        else:
            index = self.SCALE_MODES.index(self._scale_mode)
            target = index - 1 if direction > 0 else index + 1
            if not 0 <= target < len(self.SCALE_MODES):
                return False
            self._scale_mode = self.SCALE_MODES[target]
            if self._scale_mode == "day":
                self.DAY = self.MIN_DAY
        self._update_minimum_size()
        self.updateGeometry()
        self.update()
        return True

    def visible_month_label(self) -> str:
        visible = self.date_for_x(self._horizontal_offset + self.LEFT)
        if self._scale_mode == "day":
            return f"{MONTH_NAMES[visible.month]} {visible.year}"
        if self._scale_mode == "month":
            return f"MONTH · {visible.year}"
        if self._scale_mode == "quarter":
            return f"QUARTER · {visible.year}"
        return f"YEAR · {visible.year}"

    def row_for_term(self, term_id: str) -> int:
        return self._row_index("term", term_id)

    def row_for_project(self, project_id: str) -> int:
        return self._row_index("project", project_id)

    def _row_index(self, kind: str, item_id: str) -> int:
        for index, (row_kind, item) in enumerate(self._rows):
            if row_kind == kind and item.id == item_id:
                return index
        return -1

    def set_horizontal_offset(self, value: int) -> None:
        self._horizontal_offset = max(0, int(value))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), SURFACE)
        self._paint_timeline(painter)
        self._paint_rows(painter)
        self._paint_scale_boundaries(painter)
        self._paint_sticky_scale(painter)
        self._paint_fixed_columns(painter)

    def _paint_timeline(self, painter: QPainter) -> None:
        painter.fillRect(
            self.LEFT, 0, self.width() - self.LEFT, self.HEADER_HEIGHT, HEADER
        )
        if self._scale_mode == "day":
            self._paint_day_timeline(painter)
        else:
            self._paint_period_timeline(painter)
        painter.setPen(QPen(BORDER, 1))
        painter.drawLine(self.LEFT, 31, self.width(), 31)
        painter.drawLine(
            self.LEFT,
            self.HEADER_HEIGHT - 1,
            self.width(),
            self.HEADER_HEIGHT - 1,
        )
        today_x = self.x_for_date(date.today())
        painter.setPen(QPen(TODAY, 1))
        painter.drawLine(today_x, 31, today_x, self.height())

    def _paint_day_timeline(self, painter: QPainter) -> None:
        day_count = (self._end - self._start).days + 1
        painter.setFont(QFont(self.font().family(), 8))
        month_start = 0
        month_key = (self._start.year, self._start.month)
        for index in range(day_count):
            current = self._start + timedelta(days=index)
            x = self.LEFT + index * self.DAY
            if current.weekday() >= 5:
                painter.fillRect(
                    x, 31, self.DAY, self.height() - 31, QColor("#20252B")
                )
            painter.setPen(QPen(GRID, 1))
            painter.drawLine(x, 31, x, self.height())
            painter.setPen(TEXT if current == date.today() else MUTED)
            painter.drawText(
                QRectF(x, 32, self.DAY, 31),
                Qt.AlignmentFlag.AlignCenter,
                str(current.day),
            )
            next_key = (
                (current + timedelta(days=1)).year,
                (current + timedelta(days=1)).month,
            )
            if next_key != month_key or index == day_count - 1:
                left = self.LEFT + month_start * self.DAY
                width = (index - month_start + 1) * self.DAY
                if month_key[1] % 2 == 0:
                    painter.fillRect(QRectF(left, 0, width, 31), QColor("#292E36"))
                painter.setPen(TEXT)
                painter.setFont(
                    QFont(self.font().family(), 9, QFont.Weight.DemiBold)
                )
                painter.drawText(
                    QRectF(left, 0, width, 31),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{MONTH_NAMES[current.month]} {current.year}",
                )
                painter.setFont(QFont(self.font().family(), 8))
                month_start = index + 1
                month_key = next_key

    def _paint_period_timeline(self, painter: QPainter) -> None:
        periods = self._periods()
        width = self.SCALE_WIDTHS[self._scale_mode]
        year_groups: list[tuple[int, int, int]] = []
        group_year = periods[0][0].year
        group_start = 0
        for index, (period_start, _period_end) in enumerate(periods):
            x = self.LEFT + index * width
            if index % 2:
                painter.fillRect(
                    QRectF(x, 31, width, self.height() - 31),
                    QColor("#20252B"),
                )
            painter.setPen(QPen(GRID, 1))
            painter.drawLine(x, 31, x, self.height())
            if self._scale_mode == "month":
                label = MONTH_NAMES[period_start.month][:3].upper()
            elif self._scale_mode == "quarter":
                label = f"Q{((period_start.month - 1) // 3) + 1}"
            else:
                label = str(period_start.year)
            painter.setPen(TEXT)
            painter.setFont(
                QFont(self.font().family(), 8, QFont.Weight.DemiBold)
            )
            painter.drawText(
                QRectF(x, 32, width, 31),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
            next_year = (
                periods[index + 1][0].year
                if index + 1 < len(periods)
                else None
            )
            if next_year != group_year:
                year_groups.append((group_year, group_start, index))
                group_start = index + 1
                group_year = next_year or group_year
        for year, first, last in year_groups:
            x = self.LEFT + first * width
            group_width = (last - first + 1) * width
            if year % 2 == 0:
                painter.fillRect(QRectF(x, 0, group_width, 31), QColor("#292E36"))
            painter.setPen(TEXT)
            painter.setFont(
                QFont(self.font().family(), 9, QFont.Weight.DemiBold)
            )
            parent = str(year) if self._scale_mode != "year" else "YEAR SCALE"
            painter.drawText(
                QRectF(x, 0, group_width, 31),
                Qt.AlignmentFlag.AlignCenter,
                parent,
            )

    def _paint_scale_boundaries(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#596574"), 2))
        if self._scale_mode == "day":
            current = date(self._start.year, self._start.month, 1)
            if current < self._start:
                current = self._next_period(current, "month")
            while current <= self._end:
                x = self.x_for_date(current)
                painter.drawLine(x, 0, x, self.height())
                current = self._next_period(current, "month")
            return
        width = self.SCALE_WIDTHS[self._scale_mode]
        for index in range(len(self._periods()) + 1):
            x = self.LEFT + index * width
            painter.drawLine(x, 0, x, self.height())

    def _paint_sticky_scale(self, painter: QPainter) -> None:
        sticky_x = self._horizontal_offset + self.LEFT
        label = self.visible_month_label()
        width = 152 if self._scale_mode != "day" else 132
        painter.fillRect(QRectF(sticky_x, 0, width, 31), QColor("#303842"))
        painter.fillRect(QRectF(sticky_x, 29, width, 2), QColor("#4E8EBB"))
        painter.setPen(QColor("#F2F5F7"))
        painter.setFont(
            QFont(self.font().family(), 9, QFont.Weight.DemiBold)
        )
        painter.drawText(
            QRectF(sticky_x + 10, 0, width - 16, 29),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            label,
        )

    def _paint_rows(self, painter: QPainter) -> None:
        for row_index, (kind, item) in enumerate(self._rows):
            y = self.HEADER_HEIGHT + row_index * self.ROW
            painter.setPen(QPen(BORDER, 1))
            painter.drawLine(0, y + self.ROW, self.width(), y + self.ROW)
            if kind == "project":
                project: GanttProject = item
                painter.fillRect(0, y, self.width(), self.ROW, PROJECT_ROW)
                project_terms = [
                    term for term in self._terms if term.project_id == project.id
                ]
                if project_terms:
                    summary = replace(
                        project_terms[0],
                        start_date=min(term.start_date for term in project_terms),
                        end_date=max(term.end_date for term in project_terms),
                    )
                    rect = self._bar_rect(summary, y, inset=5)
                    painter.setBrush(
                        QColor("#58616B") if project.is_completed else PROJECT_BAR
                    )
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRect(rect)
                    painter.setPen(QColor("#FFFFFF"))
                    painter.setFont(
                        QFont(self.font().family(), 8, QFont.Weight.DemiBold)
                    )
                    painter.drawText(
                        rect.adjusted(8, 0, -6, 0),
                        Qt.AlignmentFlag.AlignVCenter,
                        project.title,
                    )
                continue

            term: GanttTerm = item
            selected = term.id == self._selected_term_id
            if selected:
                painter.fillRect(0, y, self.width(), self.ROW, SELECTED_ROW)
            shown = term
            if self._drag_term and self._drag_term.id == term.id:
                shown = replace(
                    term,
                    start_date=term.start_date + timedelta(days=self._drag_delta),
                    end_date=term.end_date + timedelta(days=self._drag_delta),
                )
            rect = self._bar_rect(shown, y)
            painter.setBrush(TERM_BAR_SELECTED if selected else TERM_BAR)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 2, 2)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont(self.font().family(), 8))
            painter.drawText(
                rect.adjusted(8, 0, -6, 0),
                Qt.AlignmentFlag.AlignVCenter,
                term.title,
            )

    def _paint_fixed_columns(self, painter: QPainter) -> None:
        x = self._horizontal_offset
        painter.fillRect(x, 0, self.LEFT, self.height(), LEFT_SURFACE)
        for row_index, (kind, item) in enumerate(self._rows):
            y = self.HEADER_HEIGHT + row_index * self.ROW
            selected = (
                kind == "term" and item.id == self._selected_term_id
            ) or (
                kind == "project"
                and not self._selected_term_id
                and item.id == self._selected_project_id
            )
            if kind == "project":
                painter.fillRect(
                    x, y, self.LEFT, self.ROW, SELECTED_ROW if selected else PROJECT_ROW
                )
                title_x = x + 16
                title = f"▾  {item.title}"
                start = self._project_start(item.id)
            else:
                if selected:
                    painter.fillRect(x, y, self.LEFT, self.ROW, SELECTED_ROW)
                title_x = x + 42
                title = item.title
                start = item.start_date
            painter.setFont(
                QFont(
                    self.font().family(),
                    8,
                    QFont.Weight.DemiBold if kind == "project" else QFont.Weight.Normal,
                )
            )
            painter.setPen(TEXT)
            painter.drawText(
                QRectF(title_x, y, self.NAME_WIDTH - (title_x - x) - 8, self.ROW),
                Qt.AlignmentFlag.AlignVCenter,
                title,
            )
            painter.setPen(MUTED)
            painter.drawText(
                QRectF(x + self.NAME_WIDTH + 12, y, self.LEFT - self.NAME_WIDTH - 20, self.ROW),
                Qt.AlignmentFlag.AlignVCenter,
                start.isoformat() if start else "—",
            )
            painter.setPen(QPen(BORDER, 1))
            painter.drawLine(x, y + self.ROW, x + self.LEFT, y + self.ROW)
        painter.fillRect(x, 0, self.LEFT, self.HEADER_HEIGHT, HEADER)
        painter.setPen(TEXT)
        painter.setFont(QFont(self.font().family(), 8, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(x + 14, 0, self.NAME_WIDTH - 14, self.HEADER_HEIGHT),
            Qt.AlignmentFlag.AlignVCenter,
            "PROJECT / TERM",
        )
        painter.drawText(
            QRectF(
                x + self.NAME_WIDTH + 12,
                0,
                self.LEFT - self.NAME_WIDTH - 20,
                self.HEADER_HEIGHT,
            ),
            Qt.AlignmentFlag.AlignVCenter,
            "START DATE",
        )
        painter.setPen(QPen(BORDER, 1))
        painter.drawLine(x + self.NAME_WIDTH, 0, x + self.NAME_WIDTH, self.height())
        painter.drawLine(x + self.LEFT, 0, x + self.LEFT, self.height())

    def _project_start(self, project_id: str) -> date | None:
        dates = [
            term.start_date for term in self._terms if term.project_id == project_id
        ]
        return min(dates) if dates else None

    def _bar_rect(
        self, term: GanttTerm, row_y: int, *, inset: int = 7
    ) -> QRectF:
        x = self.x_for_date(term.start_date) + 1
        end_x = self.x_for_date(term.end_date + timedelta(days=1))
        width = end_x - x - 1
        return QRectF(x, row_y + inset, max(width, 16), self.ROW - inset * 2)

    def _row_at(self, y: float) -> tuple[str, GanttProject | GanttTerm] | None:
        if y < self.HEADER_HEIGHT:
            return None
        index = int((y - self.HEADER_HEIGHT) // self.ROW)
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        row = self._row_at(event.position().y())
        if row is None:
            return super().mousePressEvent(event)
        kind, item = row
        if kind == "project":
            self.select_project(item.id)
            event.accept()
            return
        self.select_term(item.id)
        row_index = self.row_for_term(item.id)
        y = self.HEADER_HEIGHT + row_index * self.ROW
        if self._bar_rect(item, y).contains(event.position()):
            self._drag_term = item
            self._drag_origin_x = event.position().x()
            self._drag_delta = 0
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_term is None:
            return super().mouseMoveEvent(event)
        origin_date = self.date_for_x(self._drag_origin_x)
        current_date = self.date_for_x(event.position().x())
        self._drag_delta = (current_date - origin_date).days
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_term is None:
            return super().mouseReleaseEvent(event)
        term_id = self._drag_term.id
        delta = self._drag_delta
        self._drag_term = None
        self._drag_delta = 0
        self.unsetCursor()
        if delta:
            move_term_days(term_id, delta)
            self.term_moved.emit(term_id, delta)
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        row = self._row_at(event.position().y())
        if row is None:
            return super().mouseDoubleClickEvent(event)
        kind, item = row
        if kind == "project":
            self.project_edit_requested.emit(item.id)
        else:
            self.term_edit_requested.emit(item.id)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() not in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            return super().keyPressEvent(event)
        direction = -1 if event.key() == Qt.Key.Key_Up else 1
        modifiers = event.modifiers()
        if (
            modifiers & Qt.KeyboardModifier.ControlModifier
            and modifiers & Qt.KeyboardModifier.AltModifier
        ):
            action = self.ACTION_MOVE_TERM_PROJECT
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            action = self.ACTION_REORDER_TERM
        elif modifiers & Qt.KeyboardModifier.AltModifier:
            action = self.ACTION_SELECT_PROJECT
        else:
            action = self.ACTION_SELECT_TERM
        self.navigation_requested.emit(direction, action)
        event.accept()


FORM_STYLE = (
    "QDialog { background:#1B1E23; color:#E3E6EA; }"
    "QLineEdit,QComboBox,QDateEdit,QTextEdit { color:#E3E6EA; "
    "background:#14171B; border:1px solid #3A414B; padding:5px; }"
    "QPushButton { color:#E3E6EA; background:#292E36; "
    "border:1px solid #414954; padding:5px 12px; }"
)


class ProjectDialog(QDialog):
    def __init__(
        self,
        *,
        project: GanttProject | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit project" if project else "New project")
        self.setMinimumWidth(460)
        self.setStyleSheet(FORM_STYLE)
        layout = QFormLayout(self)
        self.title = QLineEdit(project.title if project else "", self)
        self.description = QTextEdit(self)
        self.description.setFixedHeight(92)
        self.description.setPlainText(project.description if project else "")
        self.completed = QCheckBox("Completed", self)
        self.completed.setChecked(project.is_completed if project else False)
        layout.addRow("Project name", self.title)
        layout.addRow("Description", self.description)
        layout.addRow("Status", self.completed)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> tuple[str, str, bool]:
        return (
            self.title.text().strip(),
            self.description.toPlainText().strip(),
            self.completed.isChecked(),
        )

    def _validate(self) -> None:
        if not self.title.text().strip():
            QMessageBox.warning(self, "Project", "Enter a project name.")
            return
        self.accept()


class TermDialog(QDialog):
    def __init__(
        self,
        projects: list[GanttProject],
        *,
        term: GanttTerm | None = None,
        default_project_id: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit term" if term else "New term")
        self.setMinimumWidth(460)
        self.setStyleSheet(FORM_STYLE)
        layout = QFormLayout(self)
        self.project = QComboBox(self)
        for project in projects:
            self.project.addItem(project.title, project.id)
        selected_project = term.project_id if term else default_project_id
        index = self.project.findData(selected_project)
        if index >= 0:
            self.project.setCurrentIndex(index)
        self.title = QLineEdit(term.title if term else "", self)
        self.description = QTextEdit(self)
        self.description.setFixedHeight(82)
        self.description.setPlainText(term.description if term else "")
        self.start = QDateEdit(self)
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat("yyyy-MM-dd")
        self.end = QDateEdit(self)
        self.end.setCalendarPopup(True)
        self.end.setDisplayFormat("yyyy-MM-dd")
        start = term.start_date if term else date.today()
        end = term.end_date if term else date.today() + timedelta(days=6)
        self.start.setDate(QDate(start.year, start.month, start.day))
        self.end.setDate(QDate(end.year, end.month, end.day))
        layout.addRow("Project", self.project)
        layout.addRow("Term name", self.title)
        layout.addRow("Description", self.description)
        layout.addRow("Start date", self.start)
        layout.addRow("End date", self.end)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> tuple[str, str, str, date, date]:
        start_q = self.start.date()
        end_q = self.end.date()
        return (
            str(self.project.currentData()),
            self.title.text().strip(),
            self.description.toPlainText().strip(),
            date(start_q.year(), start_q.month(), start_q.day()),
            date(end_q.year(), end_q.month(), end_q.day()),
        )

    def _validate(self) -> None:
        _project_id, title, _description, start, end = self.values()
        if not title:
            QMessageBox.warning(self, "Term", "Enter a term name.")
            return
        if end < start:
            QMessageBox.warning(
                self, "Term", "The end date must be on or after the start date."
            )
            return
        self.accept()


class GanttScrollArea(QScrollArea):
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


PAGE_STYLE = """
GanttPage { background:#15171B; color:#E3E6EA; }
QPushButton {
    color:#DDE2E7; background:#24282F; border:1px solid #3A414B;
    border-radius:3px; padding:4px 10px; min-height:22px;
}
QPushButton:hover { background:#2C323A; border-color:#596575; }
QPushButton:pressed, QPushButton:checked {
    background:#253C50; border-color:#4C86B3; color:#FFFFFF;
}
QComboBox {
    color:#DDE2E7; background:#1D2127; border:1px solid #3A414B;
    border-radius:3px; padding:4px 8px; min-height:22px;
}
"""


class GanttPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        ensure_gantt_tables()
        self.setStyleSheet(PAGE_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(7)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        title = QLabel("GANTT", self)
        title.setStyleSheet(
            "QLabel { color:#F1F3F5; font-size:15px; font-weight:700; "
            "letter-spacing:1px; }"
        )
        self._project_combo = QComboBox(self)
        self._project_combo.setMinimumWidth(180)
        add_project_button = QPushButton("+ Project", self)
        add_term_button = QPushButton("+ Term", self)
        edit_button = QPushButton("Edit", self)
        delete_button = QPushButton("Delete", self)
        self._filtered_project_id: str | None = None
        self._filter_button = QPushButton("Filter · All projects", self)
        self._filter_button.setToolTip("Filter Gantt rows by project")
        self._filter_menu = QMenu(self._filter_button)
        self._filter_button.setMenu(self._filter_menu)
        previous_button = QPushButton("‹ 4 weeks", self)
        today_button = QPushButton("Today", self)
        next_button = QPushButton("4 weeks ›", self)
        add_project_button.clicked.connect(self._add_project)
        add_term_button.clicked.connect(self._add_term)
        edit_button.clicked.connect(self._edit_selected)
        delete_button.clicked.connect(self._delete_selected)
        previous_button.clicked.connect(lambda: self.shift_view(-28))
        today_button.clicked.connect(self.scroll_to_today)
        next_button.clicked.connect(lambda: self.shift_view(28))
        toolbar.addWidget(title)
        toolbar.addSpacing(8)
        toolbar.addWidget(self._project_combo)
        toolbar.addWidget(add_project_button)
        toolbar.addWidget(add_term_button)
        toolbar.addWidget(edit_button)
        toolbar.addWidget(delete_button)
        toolbar.addSpacing(6)
        toolbar.addWidget(self._filter_button)
        toolbar.addStretch(1)
        toolbar.addWidget(previous_button)
        toolbar.addWidget(today_button)
        toolbar.addWidget(next_button)
        root.addLayout(toolbar)

        hint = QLabel(
            "↑↓ Select term   Alt+↑↓ Select project   Ctrl+↑↓ Reorder term   "
            "Ctrl+Alt+↑↓ Move term to project   Ctrl+± / Ctrl+Wheel Zoom   "
            "Drag Move schedule",
            self,
        )
        hint.setStyleSheet("QLabel { color:#8F98A4; font-size:9px; }")
        root.addWidget(hint)
        self._description = QLabel("DESCRIPTION  —", self)
        self._description.setWordWrap(False)
        self._description.setStyleSheet(
            "QLabel { color:#AAB2BC; background:#1B1E23; "
            "border:1px solid #30353D; padding:6px 9px; font-size:9px; }"
        )
        root.addWidget(self._description)

        self._canvas = GanttCanvas(self)
        self._canvas.term_moved.connect(self._on_term_moved)
        self._canvas.term_edit_requested.connect(self._edit_term)
        self._canvas.project_edit_requested.connect(self._edit_project)
        self._canvas.navigation_requested.connect(self._on_navigation_requested)
        self._canvas.term_selected.connect(self._show_term_description)
        self._canvas.project_selected.connect(self._on_project_selected)
        self._scroll = GanttScrollArea(self)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(self._canvas)
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll.viewport().setStyleSheet("background:#15171B;")
        self._scroll.horizontalScrollBar().setStyleSheet(
            "QScrollBar:horizontal { background:#111317; height:9px; }"
            "QScrollBar::handle:horizontal { background:#47515E; "
            "min-width:44px; border-radius:4px; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal "
            "{ width:0; border:none; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal "
            "{ background:transparent; }"
        )
        self._extending_timeline = False
        self._scroll.horizontalScrollBar().valueChanged.connect(
            self._on_horizontal_scroll_changed
        )
        self._scroll.zoom_requested.connect(self.zoom_timeline)
        self._zoom_in_shortcut = QShortcut(QKeySequence("Ctrl++"), self)
        self._zoom_in_equal_shortcut = QShortcut(
            QKeySequence("Ctrl+="), self
        )
        self._zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self)
        for shortcut in (
            self._zoom_in_shortcut,
            self._zoom_in_equal_shortcut,
            self._zoom_out_shortcut,
        ):
            shortcut.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
        self._zoom_in_shortcut.activated.connect(
            lambda: self.zoom_timeline(1)
        )
        self._zoom_in_equal_shortcut.activated.connect(
            lambda: self.zoom_timeline(1)
        )
        self._zoom_out_shortcut.activated.connect(
            lambda: self.zoom_timeline(-1)
        )
        root.addWidget(self._scroll, 1)
        self._did_initial_scroll = False
        self.reload()

    @property
    def filtered_project_id(self) -> str | None:
        return self._filtered_project_id

    def reload(self) -> None:
        current_project = str(self._project_combo.currentData() or "")
        selected_term = self._canvas.selected_term_id
        selected_project = self._canvas.selected_project_id
        all_projects = list_projects(include_completed=True)
        all_project_ids = {project.id for project in all_projects}
        if self._filtered_project_id not in all_project_ids:
            self._filtered_project_id = None
        projects = [
            project
            for project in all_projects
            if self._filtered_project_id is None
            or project.id == self._filtered_project_id
        ]
        project_ids = {project.id for project in projects}
        terms = [
            term for term in list_terms() if term.project_id in project_ids
        ]
        self._rebuild_project_filter_menu(all_projects)
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        for project in projects:
            suffix = "  ✓" if project.is_completed else ""
            self._project_combo.addItem(project.title + suffix, project.id)
        index = self._project_combo.findData(current_project)
        if index >= 0:
            self._project_combo.setCurrentIndex(index)
        self._project_combo.blockSignals(False)
        self._canvas.set_rows(projects, terms)
        if selected_term:
            self._canvas.select_term(selected_term)
        elif selected_project:
            self._canvas.select_project(selected_project)
        if not self._did_initial_scroll:
            self._did_initial_scroll = True
            QTimer.singleShot(0, self.scroll_to_today)

    def _rebuild_project_filter_menu(
        self, projects: list[GanttProject]
    ) -> None:
        self._filter_menu.clear()

        all_action = self._filter_menu.addAction("All projects")
        all_action.setCheckable(True)
        all_action.setChecked(self._filtered_project_id is None)
        all_action.triggered.connect(
            lambda _checked=False: self._set_project_filter(None)
        )

        if projects:
            self._filter_menu.addSeparator()
        for project in projects:
            label = project.title
            if project.is_completed:
                label += "  (Completed)"
            action = self._filter_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(project.id == self._filtered_project_id)
            action.triggered.connect(
                lambda _checked=False, project_id=project.id:
                self._set_project_filter(project_id)
            )

        selected = next(
            (
                project
                for project in projects
                if project.id == self._filtered_project_id
            ),
            None,
        )
        if selected is None:
            self._filter_button.setText("Filter · All projects")
            self._filter_button.setToolTip("Filter Gantt rows by project")
            return
        display_title = selected.title
        if len(display_title) > 24:
            display_title = display_title[:23] + "…"
        self._filter_button.setText(f"Filter · {display_title}")
        self._filter_button.setToolTip(
            f"Showing only project: {selected.title}"
        )

    def _set_project_filter(self, project_id: str | None) -> None:
        self._filtered_project_id = project_id or None
        self.reload()

    def add_term(self) -> None:
        self._add_term()

    def _timeline_extension_days(self) -> int:
        return extension_days(self._canvas.scale_mode)

    def _on_horizontal_scroll_changed(self, value: int) -> None:
        self._canvas.set_horizontal_offset(value)
        if self._extending_timeline:
            return

        bar = self._scroll.horizontalScrollBar()
        maximum = bar.maximum()
        if maximum <= 0:
            return
        threshold = max(160, min(800, bar.pageStep() // 2))
        extend_before = value <= threshold
        extend_after = maximum - value <= threshold
        if not extend_before and not extend_after:
            return

        chunk = self._timeline_extension_days()
        self._extending_timeline = True
        try:
            prepend_shift = self._canvas.extend_timeline(
                before_days=chunk if extend_before else 0,
                after_days=chunk if extend_after else 0,
            )
            if prepend_shift:
                bar.setValue(value + prepend_shift)
            self._canvas.set_horizontal_offset(bar.value())
        finally:
            self._extending_timeline = False

    def _ensure_date_in_timeline(self, target: date) -> None:
        chunk = self._timeline_extension_days()
        before_days = 0
        after_days = 0
        if target < self._canvas.timeline_start:
            before_days = max(
                chunk, (self._canvas.timeline_start - target).days + 28
            )
        if target > self._canvas.timeline_end:
            after_days = max(
                chunk, (target - self._canvas.timeline_end).days + 28
            )
        if before_days or after_days:
            self._canvas.extend_timeline(
                before_days=before_days, after_days=after_days
            )

    def scroll_to_today(self) -> None:
        self._ensure_date_in_timeline(date.today())
        x = self._canvas.x_for_date(date.today())
        available = max(1, self._scroll.viewport().width() - self._canvas.LEFT)
        self._scroll.horizontalScrollBar().setValue(
            max(0, x - self._canvas.LEFT - available // 3)
        )

    def shift_view(self, days: int) -> None:
        bar = self._scroll.horizontalScrollBar()
        visible_date = self._canvas.date_for_x(
            bar.value() + self._canvas.LEFT
        )
        target = visible_date + timedelta(days=int(days))
        self._ensure_date_in_timeline(target)
        bar.setValue(
            self._canvas.x_for_date(target) - self._canvas.LEFT
        )

    def zoom_timeline(
        self, direction: int, viewport_x: int | None = None
    ) -> bool:
        viewport_width = self._scroll.viewport().width()
        if viewport_x is None or viewport_x <= self._canvas.LEFT:
            available = max(1, viewport_width - self._canvas.LEFT)
            viewport_x = self._canvas.LEFT + available // 2
        bar = self._scroll.horizontalScrollBar()
        anchor_date = self._canvas.date_for_x(bar.value() + viewport_x)
        if not self._canvas.change_zoom(direction):
            return False
        bar.setValue(self._canvas.x_for_date(anchor_date) - viewport_x)
        return True

    def move_selection(self, direction: int) -> bool:
        terms = self._canvas.terms
        if not terms:
            return False
        current = self._canvas.selected_term()
        project_id = (
            current.project_id if current else self._canvas.selected_project_id
        )
        siblings = [term for term in terms if term.project_id == project_id]
        if not siblings:
            target = terms[0 if direction >= 0 else -1]
        elif current is None:
            target = siblings[0 if direction >= 0 else -1]
        else:
            index = siblings.index(current)
            target = siblings[
                max(0, min(len(siblings) - 1, index + direction))
            ]
        self._canvas.select_term(target.id)
        self._ensure_row_visible(self._canvas.row_for_term(target.id))
        return True

    def navigate_project(self, direction: int) -> bool:
        projects = self._canvas.projects
        if not projects:
            return False
        current_id = self._canvas.selected_project_id
        ids = [project.id for project in projects]
        if current_id not in ids:
            target_index = 0 if direction >= 0 else len(ids) - 1
        else:
            target_index = max(
                0, min(len(ids) - 1, ids.index(current_id) + direction)
            )
        project_id = ids[target_index]
        terms = [
            term for term in self._canvas.terms if term.project_id == project_id
        ]
        if terms:
            self._canvas.select_term(terms[0].id)
            row = self._canvas.row_for_term(terms[0].id)
        else:
            self._canvas.select_project(project_id)
            row = self._canvas.row_for_project(project_id)
        self._ensure_row_visible(row)
        return True

    def reorder_selected_term(self, direction: int) -> bool:
        term_id = self._canvas.selected_term_id
        if not term_id or not reorder_term(term_id, direction):
            return False
        self.reload()
        self._canvas.select_term(term_id)
        self._ensure_row_visible(self._canvas.row_for_term(term_id))
        return True

    def move_selected_to_project(self, direction: int) -> bool:
        term = self._canvas.selected_term()
        projects = self._canvas.projects
        if term is None or len(projects) < 2:
            return False
        ids = [project.id for project in projects]
        current_index = ids.index(term.project_id)
        target_index = current_index + direction
        if not 0 <= target_index < len(ids):
            return False
        if not move_term_to_project(term.id, ids[target_index]):
            return False
        self.reload()
        self._canvas.select_term(term.id)
        self._ensure_row_visible(self._canvas.row_for_term(term.id))
        return True

    def _ensure_row_visible(self, row: int) -> None:
        if row < 0:
            return
        y = self._canvas.HEADER_HEIGHT + row * self._canvas.ROW
        self._scroll.verticalScrollBar().setValue(
            max(0, y - self._scroll.viewport().height() // 2)
        )

    def _on_navigation_requested(self, direction: int, action: int) -> None:
        if action == self._canvas.ACTION_SELECT_PROJECT:
            self.navigate_project(direction)
        elif action == self._canvas.ACTION_REORDER_TERM:
            self.reorder_selected_term(direction)
        elif action == self._canvas.ACTION_MOVE_TERM_PROJECT:
            self.move_selected_to_project(direction)
        else:
            self.move_selection(direction)

    def _add_project(self) -> None:
        dialog = ProjectDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        title, description, completed = dialog.values()
        project_id = add_project(
            title, description=description, is_completed=completed
        )
        self.reload()
        index = self._project_combo.findData(project_id)
        if index >= 0:
            self._project_combo.setCurrentIndex(index)
        self._canvas.select_project(project_id)

    def _edit_selected(self) -> None:
        if self._canvas.selected_term_id:
            self._edit_term(self._canvas.selected_term_id)
            return
        project_id = (
            self._canvas.selected_project_id
            or str(self._project_combo.currentData() or "")
        )
        if project_id:
            self._edit_project(project_id)

    def _edit_project(self, project_id: str) -> None:
        project = next(
            (
                item
                for item in list_projects(include_completed=True)
                if item.id == project_id
            ),
            None,
        )
        if project is None:
            return
        dialog = ProjectDialog(project=project, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        title, description, completed = dialog.values()
        update_project(project_id, title, description, completed)
        self.reload()

    def _add_term(self) -> None:
        projects = list_projects(include_completed=True)
        if not projects:
            QMessageBox.information(
                self, "Gantt", "Create a project before adding a term."
            )
            return
        dialog = TermDialog(
            projects,
            default_project_id=str(self._project_combo.currentData() or ""),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        project_id, title, description, start, end = dialog.values()
        term_id = add_term(
            project_id,
            title,
            start,
            end,
            description=description,
            color="#2F78D8",
        )
        self.reload()
        self._canvas.select_term(term_id)

    def _edit_term(self, term_id: str) -> None:
        term = next((item for item in list_terms() if item.id == term_id), None)
        if term is None:
            return
        dialog = TermDialog(
            list_projects(include_completed=True), term=term, parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        project_id, title, description, start, end = dialog.values()
        update_term(
            term_id,
            project_id,
            title,
            start,
            end,
            description=description,
            color="#2F78D8",
        )
        self.reload()

    def _delete_selected(self) -> None:
        if self._canvas.selected_term_id:
            self._delete_term()
            return
        project_id = (
            self._canvas.selected_project_id
            or str(self._project_combo.currentData() or "")
        )
        if not project_id:
            return
        project = next(
            (
                item
                for item in list_projects(include_completed=True)
                if item.id == project_id
            ),
            None,
        )
        if project is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete project",
            f'Delete "{project.title}" and all of its terms?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            delete_project(project_id)
            self.reload()

    def _delete_term(self) -> None:
        term_id = self._canvas.selected_term_id
        if not term_id:
            return
        answer = QMessageBox.question(
            self,
            "Delete term",
            "Delete the selected term?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            delete_term(term_id)
            self.reload()

    def _on_term_moved(self, _term_id: str, _days: int) -> None:
        self.reload()

    def _on_project_selected(self, project_id: str) -> None:
        index = self._project_combo.findData(project_id)
        if index >= 0:
            self._project_combo.setCurrentIndex(index)
        if not self._canvas.selected_term_id:
            project = next(
                (item for item in self._canvas.projects if item.id == project_id),
                None,
            )
            description = project.description if project else ""
            self._description.setText(
                f"DESCRIPTION  {description or '—'}"
            )

    def _show_term_description(self, term_id: str) -> None:
        term = next(
            (item for item in self._canvas.terms if item.id == term_id),
            None,
        )
        self._description.setText(
            f"DESCRIPTION  {(term.description if term else '') or '—'}"
        )
