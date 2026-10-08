"""カンバン用の軽量タスクカード（QTextBrowser 不使用・タイトルは QLabel の省略表示）。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fluxel.core.description_storage import preview_plain_one_line_fast
from fluxel.kanban.task_dates import end_date_category, format_end_date_jp


class ElidedTitleLabel(QLabel):
    """1 行省略（カスタム paint＋グラデより描画コストを抑える）。"""

    def __init__(self, full_text: str, color_hex: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = full_text or "(no name)"
        self.setToolTip(self._full)
        self.setWordWrap(False)
        self.setStyleSheet(
            f"QLabel {{ border: none; background: transparent; font-size: 12px; "
            f"font-weight: 500; color: {color_hex}; padding: 0px; margin: 0px; }}"
        )
        f = self.font()
        f.setPointSize(12)
        f.setWeight(QFont.Weight.Medium)
        self.setFont(f)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._fm = QFontMetrics(self.font())
        self.setMinimumHeight(self._fm.height() + 12)
        self._last_elide_w = -1
        self._apply_elide()

    def resizeEvent(self, event) -> None:
        w = event.size().width()
        if w == self._last_elide_w:
            super().resizeEvent(event)
            return
        self._apply_elide()
        super().resizeEvent(event)

    def _apply_elide(self) -> None:
        w = max(self.width(), 48)
        if w == self._last_elide_w:
            return
        self._last_elide_w = w
        self.setText(self._fm.elidedText(self._full, Qt.TextElideMode.ElideRight, w - 4))


class TaskCardWidget(QFrame):
    """クリック可能なタスクカード。説明は1行プレビュー。"""

    clicked = Signal(str)
    hover_entered = Signal(str)

    def __init__(
        self,
        task_id: str,
        status: str,
        task_name: str,
        end_date: str,
        description_raw: str,
        importance_color: str,
        desc_color: str,
        title_text_color: QColor,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.task_id = task_id
        self.status = (status or "").strip().lower()
        self._selected = False
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QFrame { border: none; background: transparent; }")
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        card_layout = QHBoxLayout(self)
        card_layout.setContentsMargins(2, 2, 2, 2)
        card_layout.setSpacing(4)

        color_bar = QFrame(self)
        color_bar.setFixedWidth(6)
        color_bar.setStyleSheet(
            f"QFrame {{ background-color: {importance_color}; border: none; }}"
        )
        card_layout.addWidget(color_bar)

        self._content = QWidget(self)
        self._content.setStyleSheet("QWidget { background: transparent; border: none; }")
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(6, 2, 6, 2)
        content_layout.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        title_hex = title_text_color.name(QColor.NameFormat.HexRgb)
        title_text = task_name or "(no name)"
        self._title_label = ElidedTitleLabel(title_text, title_hex, self._content)
        top_row.addWidget(self._title_label, 1)

        date_display = format_end_date_jp(end_date)
        meta_label = QLabel(date_display, self._content)
        meta_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        meta_label.setWordWrap(False)
        cat = end_date_category(end_date)
        if cat == "today":
            meta_label.setStyleSheet(
                "QLabel { border: 1px solid #FF9800; border-radius: 4px; "
                "background: transparent; padding: 2px 6px; margin: 0px; "
                "font-size: 11px; color: #FF9800; }"
            )
        elif cat == "past":
            meta_label.setStyleSheet(
                "QLabel { border: 1px solid #E53935; border-radius: 4px; "
                "background: transparent; padding: 2px 6px; margin: 0px; "
                "font-size: 11px; color: #E53935; }"
            )
        else:
            meta_label.setStyleSheet(
                f"QLabel {{ border: none; background: transparent; padding: 0px; "
                f"margin: 0px; font-size: 11px; color: {desc_color}; }}"
            )
        meta_fm = QFontMetrics(meta_label.font())
        meta_label.setMinimumWidth(
            max(meta_fm.horizontalAdvance(date_display) + 16, 1)
        )
        meta_label.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        meta_label.setFixedHeight(self._title_label.minimumHeight())
        top_row.addWidget(meta_label, 0)
        content_layout.addLayout(top_row)

        preview = preview_plain_one_line_fast(description_raw or "", max_len=160)
        desc_label = QLabel(preview or " ", self._content)
        desc_label.setWordWrap(False)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        desc_label.setStyleSheet(
            f"QLabel {{ border: none; background: transparent; font-size: 11px; "
            f"color: {desc_color}; padding: 0px; }}"
        )
        desc_label.setFixedHeight(46)
        content_layout.addWidget(desc_label)

        card_layout.addWidget(self._content, 1)

        self._right_sel = QFrame(self)
        self._right_sel.setFixedWidth(3)
        self._right_sel.setStyleSheet(
            "QFrame { background-color: #757575; border: none; }"
        )
        self._right_sel.hide()
        card_layout.addWidget(self._right_sel)

        self._content.installEventFilter(self)

    def enterEvent(self, event) -> None:
        self.hover_entered.emit(self.task_id)
        super().enterEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._content and event.type() == QEvent.Type.Enter:
            self.hover_entered.emit(self.task_id)
        return False

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        if selected:
            self.setStyleSheet(
                "QFrame { border: 1px solid #757575; border-radius: 4px; "
                "background: transparent; }"
            )
            self._right_sel.show()
        else:
            self.setStyleSheet(
                "QFrame { border: none; background: transparent; }"
            )
            self._right_sel.hide()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.task_id)
        super().mousePressEvent(event)
