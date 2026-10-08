"""Tasks.db を対象としたタスク検索（Kanban 風カード・ポップアップ用フォーム）。"""

from __future__ import annotations

import html
import re
import sqlite3
from collections.abc import Callable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fluxel.core.fluxel_db import TASK_DB
from fluxel.core.fluxel_status import STATUS_UI_CHOICES
from fluxel.core.description_storage import preview_plain_one_line_fast, strip_storage_markers
from fluxel.kanban.task_dates import end_date_category, format_end_date_jp

_STATUS_LABEL: dict[str, str] = {k: label for label, k in STATUS_UI_CHOICES}


def _status_display(status_key: str) -> str:
    return _STATUS_LABEL.get((status_key or "").strip().lower(), status_key or "—")


def _html_highlight(text: str, query: str) -> str:
    """プレーン文字列をエスケープし、query に一致する部分を <b> で囲む。"""
    t = text or ""
    q = (query or "").strip()
    if not q:
        return html.escape(t)
    terms = [term for term in re.split(r"\s+", q) if term]
    pat = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
    out: list[str] = []
    last = 0
    for m in pat.finditer(t):
        out.append(html.escape(t[last : m.start()]))
        out.append("<b>" + html.escape(m.group()) + "</b>")
        last = m.end()
    out.append(html.escape(t[last:]))
    return "".join(out)


def _end_date_sort_key(end_date: str | None) -> str:
    ed = (end_date or "").strip()
    if not ed:
        return "9999-99-99"
    return ed[:10].replace("/", "-")


def _sort_search_rows(rows: list[tuple]) -> list[tuple]:
    """
    Archive 以外を先に、各グループ内は end_date 昇順（空は後ろ）、同一日は名前。
    """

    def key(r: tuple) -> tuple:
        _id, name, _desc, end_date, status, _imp = r
        st = (status or "").strip().lower()
        arch = 1 if st == "archive" else 0
        return (arch, _end_date_sort_key(end_date), (name or "").lower(), _id or "")

    return sorted(rows, key=key)


def fetch_search_results(
    query: str,
    *,
    include_archive: bool,
    status_filter: str = "",
    importance_filter: str = "",
) -> tuple[list[tuple], list[tuple]]:
    """Return title matches and content matches with optional enterprise filters."""
    q = (query or "").strip()
    status_filter = (status_filter or "").strip().lower()
    importance_filter = (importance_filter or "").strip().lower()
    if not q and not status_filter and not importance_filter:
        return [], []

    terms = [term for term in re.split(r"\s+", q.lower()) if term]
    conn = sqlite3.connect(TASK_DB)
    cur = conn.cursor()
    where_parts: list[str] = []
    params: list[str] = []
    for term in terms:
        where_parts.append(
            "(lower(name) LIKE ? OR lower(COALESCE(description, '')) LIKE ?)"
        )
        like = f"%{term}%"
        params.extend((like, like))
    if status_filter:
        where_parts.append("lower(trim(status)) = ?")
        params.append(status_filter)
    elif not include_archive:
        where_parts.append("lower(trim(status)) != 'archive'")
    if importance_filter:
        aliases = {
            "high": ("高", "high"),
            "medium": ("中", "medium", "normal"),
            "low": ("低", "low"),
        }.get(importance_filter, (importance_filter,))
        where_parts.append(
            "lower(trim(COALESCE(importance, ''))) IN (%s)"
            % ", ".join("?" for _ in aliases)
        )
        params.extend(value.lower() for value in aliases)
    where_sql = " AND ".join(where_parts) if where_parts else "1=1"
    cur.execute(
        f"""
        SELECT id, name, description, end_date, status, importance
        FROM tasks
        WHERE {where_sql}
        """,
        tuple(params),
    )
    raw = cur.fetchall()
    conn.close()

    title_rows: list[tuple] = []
    body_rows: list[tuple] = []
    seen_title: set[str] = set()
    for row in raw:
        task_id, name, desc, _end_date, _status, _importance = row
        task_id = task_id or ""
        name_lower = (name or "").lower()
        description_lower = strip_storage_markers(desc or "").lower()
        if not terms or all(term in name_lower for term in terms):
            title_rows.append(row)
            seen_title.add(task_id)
        elif all(term in name_lower or term in description_lower for term in terms):
            body_rows.append(row)

    return (
        _sort_search_rows(title_rows),
        _sort_search_rows([row for row in body_rows if (row[0] or "") not in seen_title]),
    )


class TaskSearchResultCard(QFrame):
    clicked = Signal(str)

    def __init__(
        self,
        task_id: str,
        status: str,
        task_name: str,
        end_date: str,
        description_raw: str,
        importance_color: str,
        desc_color: str,
        title_color_hex: str,
        query: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.task_id = task_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("searchResultCard")
        self._normal_style = (
            "QFrame#searchResultCard { background: #20252c; border: 1px solid #343b46; border-radius: 7px; }"
            "QFrame#searchResultCard:hover { background: #252b33; border-color: #4b5868; }"
        )
        self._active_style = (
            "QFrame#searchResultCard { background: #25354a; border: 1px solid #5d9cec; border-radius: 7px; }"
        )
        self.setStyleSheet(self._normal_style)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(76)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(11)
        color_bar = QFrame(self)
        color_bar.setFixedWidth(4)
        color_bar.setStyleSheet(
            f"QFrame {{ background: {importance_color}; border: none; border-radius: 2px; }}"
        )
        layout.addWidget(color_bar)

        content = QVBoxLayout()
        content.setContentsMargins(0, 9, 0, 8)
        content.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel(self)
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setText(
            f"<span style='color:{title_color_hex}; font-size:13px; font-weight:600;'>"
            f"{_html_highlight(task_name or '(No name)', query)}</span>"
        )
        title.setToolTip(task_name or "")
        top.addWidget(title, 1)

        status_key = (status or "").strip().lower()
        status_text = {
            "wait": "WAIT", "todo": "TODO", "doing": "DOING",
            "finish": "FINISH", "archive": "ARCHIVE",
        }.get(status_key, status_key.upper() or "—")
        status_colors = {
            "wait": ("#8b949e", "#252a30"),
            "todo": ("#77aef4", "#1d3047"),
            "doing": ("#dfb45c", "#3b301b"),
            "finish": ("#73c991", "#1c3827"),
            "archive": ("#9da4ae", "#2b2f35"),
        }
        foreground, background = status_colors.get(status_key, (desc_color, "#292e35"))
        status_label = QLabel(status_text, self)
        status_label.setStyleSheet(
            f"QLabel {{ color: {foreground}; background: {background}; border: none; "
            "border-radius: 4px; padding: 2px 7px; font-size: 9px; font-weight: 700; }}"
        )
        top.addWidget(status_label)

        date_label = QLabel(format_end_date_jp(end_date), self)
        category = end_date_category(end_date)
        date_color = "#ef858f" if category == "past" else "#e9b95f" if category == "today" else desc_color
        date_label.setStyleSheet(
            f"QLabel {{ color: {date_color}; background: transparent; border: none; font-size: 11px; }}"
        )
        top.addWidget(date_label)
        content.addLayout(top)

        preview = preview_plain_one_line_fast(strip_storage_markers(description_raw or ""), max_len=180)
        description = QLabel(self)
        description.setTextFormat(Qt.TextFormat.RichText)
        description.setText(
            f"<span style='color:{desc_color}; font-size:11px;'>"
            f"{_html_highlight(preview or 'No description', query)}</span>"
        )
        content.addWidget(description)
        layout.addLayout(content, 1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.task_id)
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        self.setStyleSheet(self._active_style if active else self._normal_style)


class TaskSearchForm(QWidget):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        importance_color_fn: Callable[[str], str],
        is_dark_fn: Callable[[], bool],
        open_task: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._importance_color_fn = importance_color_fn
        self._is_dark_fn = is_dark_fn
        self._open_task = open_task
        self._pending_query = ""
        self._active_query = ""
        self._selected_index = -1
        self._visible_cards: list[TaskSearchResultCard] = []
        self._selected_card: TaskSearchResultCard | None = None
        self._selection_mode = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("SEARCH TASKS", self)
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f3f6fa;")
        subtitle = QLabel("Search task names and descriptions", self)
        subtitle.setStyleSheet("color: #8f99a7; font-size: 11px;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self._result_summary = QLabel("Start typing to search", self)
        self._result_summary.setStyleSheet("color: #8f99a7; font-size: 11px;")
        header.addWidget(self._result_summary)
        root.addLayout(header)

        self._line = QLineEdit(self)
        self._line.setPlaceholderText("Search by task name or description...")
        self._line.setClearButtonEnabled(True)
        self._line.setMinimumHeight(38)
        self._line.setStyleSheet(
            "QLineEdit { background: #171b20; color: #edf2f7; border: 1px solid #3a4350; "
            "border-radius: 6px; padding: 0 12px; font-size: 13px; }"
            "QLineEdit:focus { border-color: #5d9cec; }"
        )
        root.addWidget(self._line)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filter_label = QLabel("FILTERS", self)
        filter_label.setStyleSheet("color: #7f8996; font-size: 9px; font-weight: 700;")
        filters.addWidget(filter_label)
        self._status_combo = QComboBox(self)
        self._status_combo.addItem("All active statuses", "")
        for label, value in (
            ("Wait", "wait"), ("Todo", "todo"), ("Doing", "doing"),
            ("Finish", "finish"), ("Archive", "archive"),
        ):
            self._status_combo.addItem(label, value)
        self._importance_combo = QComboBox(self)
        self._importance_combo.addItem("All importance", "")
        self._importance_combo.addItem("High", "high")
        self._importance_combo.addItem("Medium", "medium")
        self._importance_combo.addItem("Low", "low")
        self._archive_cb = QCheckBox("Include Archive", self)
        filters.addWidget(self._status_combo)
        filters.addWidget(self._importance_combo)
        filters.addWidget(self._archive_cb)
        filters.addStretch(1)
        keyboard = QLabel("↑↓ Select   Enter Open   Esc Close", self)
        keyboard.setStyleSheet("color: #747f8d; font-size: 10px;")
        filters.addWidget(keyboard)
        root.addLayout(filters)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMinimumHeight(360)
        self._scroll.setMaximumHeight(580)
        self._results_body = QWidget(self._scroll)
        self._results_body.setStyleSheet("background: transparent;")
        self._results_layout = QVBoxLayout(self._results_body)
        self._results_layout.setContentsMargins(0, 2, 0, 2)
        self._results_layout.setSpacing(7)
        self._results_layout.addStretch(1)
        self._scroll.setWidget(self._results_body)
        root.addWidget(self._scroll, 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(160)
        self._search_timer.timeout.connect(self.execute_search_now)
        self._line.textChanged.connect(self._on_query_changed)
        self._line.returnPressed.connect(self.execute_search_now)
        self._line.returnPressed.connect(self._on_line_return_pressed)
        self._archive_cb.toggled.connect(self.execute_search_now)
        self._status_combo.currentIndexChanged.connect(self.execute_search_now)
        self._importance_combo.currentIndexChanged.connect(self.execute_search_now)

    def search_line_edit(self) -> QLineEdit:
        return self._line

    def focus_search_line(self) -> None:
        self._line.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._line.selectAll()
        self._selection_mode = False

    def refresh_results(self) -> None:
        self.execute_search_now()

    def move_selection(self, step: int) -> bool:
        if not self._visible_cards:
            return False
        if self._selected_card not in self._visible_cards:
            self._selected_index = 0 if step >= 0 else len(self._visible_cards) - 1
        else:
            index = self._visible_cards.index(self._selected_card)
            self._selected_index = max(0, min(len(self._visible_cards) - 1, index + step))
        self._selection_mode = True
        self._apply_selection()
        return True

    def activate_selected(self) -> bool:
        if 0 <= self._selected_index < len(self._visible_cards):
            card = self._visible_cards[self._selected_index]
            card.clicked.emit(card.task_id)
            return True
        return False

    def move_pane(self, _step: int) -> bool:
        return False

    def _on_query_changed(self, _text: str) -> None:
        self._pending_query = self._line.text()
        self._selection_mode = False
        self._search_timer.start()

    def _clear_results(self) -> None:
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def execute_search_now(self) -> None:
        self._search_timer.stop()
        window = self.window()
        if window is not None and not window.isVisible():
            return
        query = self._pending_query
        self._active_query = query
        status_filter = str(self._status_combo.currentData() or "")
        importance_filter = str(self._importance_combo.currentData() or "")
        title_rows, body_rows = fetch_search_results(
            query,
            include_archive=self._archive_cb.isChecked(),
            status_filter=status_filter,
            importance_filter=importance_filter,
        )
        self._clear_results()
        self._visible_cards = []
        self._selected_card = None
        self._selected_index = -1
        self._selection_mode = False
        dark = self._is_dark_fn()
        description_color = "#aeb7c3" if dark else "#4b5563"
        title_color = "#f0f4f8" if dark else "#17202a"

        def add_group(label_text: str, rows: list[tuple]) -> None:
            if not rows:
                return
            label = QLabel(f"{label_text}   {len(rows)}", self._results_body)
            label.setStyleSheet(
                "color: #7f8a98; font-size: 9px; font-weight: 700; padding: 6px 2px 1px 2px;"
            )
            self._results_layout.insertWidget(self._results_layout.count() - 1, label)
            for row in rows:
                task_id, name, desc, end_date, status, importance = row
                card = TaskSearchResultCard(
                    task_id=task_id or "",
                    status=(status or "").strip().lower(),
                    task_name=name or "",
                    end_date=end_date or "",
                    description_raw=desc or "",
                    importance_color=self._importance_color_fn(importance or ""),
                    desc_color=description_color,
                    title_color_hex=title_color,
                    query=query,
                    parent=self._results_body,
                )
                card.clicked.connect(self._on_card_clicked)
                self._results_layout.insertWidget(self._results_layout.count() - 1, card)
                self._visible_cards.append(card)

        add_group("TITLE MATCHES", title_rows)
        add_group("DESCRIPTION MATCHES", body_rows)
        if not self._visible_cards:
            has_filter = bool(status_filter or importance_filter)
            message = "No tasks match the current search and filters." if query.strip() or has_filter else "Enter a search term to find tasks."
            empty = QLabel(message, self._results_body)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(180)
            empty.setStyleSheet("color: #7f8996; font-size: 12px;")
            self._results_layout.insertWidget(self._results_layout.count() - 1, empty)
        total = len(self._visible_cards)
        self._result_summary.setText(f"{total} results" if query.strip() or status_filter or importance_filter else "Start typing to search")
        if self._visible_cards:
            self._selected_index = 0
            self._apply_selection()

    def _on_line_return_pressed(self) -> None:
        if self._visible_cards:
            self.activate_selected()

    def _on_card_clicked(self, task_id: str) -> None:
        self._selection_mode = True
        self._open_task(task_id)

    def is_selection_mode(self) -> bool:
        return self._selection_mode and self._selected_card is not None

    def has_pending_query(self) -> bool:
        return self._pending_query != self._active_query

    def has_selected_card(self) -> bool:
        return self._selected_card is not None

    def _apply_selection(self) -> None:
        if not self._visible_cards:
            return
        previous = self._selected_card
        selected = self._visible_cards[self._selected_index]
        if previous is not None and previous is not selected:
            previous.set_active(False)
        selected.set_active(True)
        self._selected_card = selected
        self._scroll.ensureWidgetVisible(selected, 8, 8)


class TaskSearchPopup(QFrame):
    """フローティング検索ポップアップ（Kanban に埋め込まない）。"""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        importance_color_fn: Callable[[str], str],
        is_dark_fn: Callable[[], bool],
        open_task: Callable[[str], None],
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("TaskSearchPopup")
        self.setStyleSheet(
            "#TaskSearchPopup { background-color: #191d22; border: 1px solid #3d4652; "
            "border-radius: 10px; }"
        )
        self.setMinimumWidth(640)
        self.setMaximumWidth(820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._form = TaskSearchForm(
            self,
            importance_color_fn=importance_color_fn,
            is_dark_fn=is_dark_fn,
            open_task=open_task,
        )
        lay.addWidget(self._form)

    def search_line_edit(self) -> QLineEdit:
        return self._form.search_line_edit()

    def focus_search_line(self) -> None:
        self._form.focus_search_line()

    def move_selection(self, step: int) -> bool:
        return self._form.move_selection(step)

    def activate_selected(self) -> bool:
        return self._form.activate_selected()

    def move_pane(self, step: int) -> bool:
        return self._form.move_pane(step)

    def execute_search_now(self) -> None:
        self._form.execute_search_now()

    def is_selection_mode(self) -> bool:
        return self._form.is_selection_mode()

    def has_pending_query(self) -> bool:
        return self._form.has_pending_query()

    def has_selected_card(self) -> bool:
        return self._form.has_selected_card()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            moved = self._form.move_selection(-1 if event.key() == Qt.Key.Key_Up else 1)
            if moved:
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            moved = self._form.move_pane(-1 if event.key() == Qt.Key.Key_Left else 1)
            if moved:
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._form.activate_selected():
                event.accept()
                return
        super().keyPressEvent(event)

    def show_near_anchor(self, anchor: QWidget, *, focus_line: bool) -> None:
        """anchor の直下付近に表示。focus_line が True のとき検索欄にフォーカス。"""
        scr = anchor.screen()
        ag = scr.availableGeometry() if scr is not None else QGuiApplication.primaryScreen().availableGeometry()
        self.show()
        self.adjustSize()
        w = min(max(self.sizeHint().width(), self.minimumWidth()), self.maximumWidth())
        h = min(self.sizeHint().height(), ag.height() - 24)
        self.resize(w, h)

        gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
        x = gp.x()
        # トリガーとの隙間で Leave が発火しないようわずかに重ねる
        y = gp.y() - 4
        if x + w > ag.right() - 8:
            x = ag.right() - w - 8
        if x < ag.left() + 8:
            x = ag.left() + 8
        if y + h > ag.bottom() - 8:
            y = gp.y() - h - 2
        if y < ag.top() + 8:
            y = ag.top() + 8
        self.move(x, y)
        self.raise_()
        self._form.refresh_results()
        if focus_line:
            self.activateWindow()
            self._form.focus_search_line()
