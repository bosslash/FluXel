"""新規・編集で共通のタスク入力 UI（Ctrl+Enter で OK と同じ確定）。"""

import sqlite3
import uuid
from datetime import datetime

from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import QDate, Qt

from fluxel.core.description_storage import (
    http_urls_for_title_fetch,
    normalize_description_for_storage,
    storage_to_display_html,
)
from fluxel.core.fluxel_db import TASK_DB
from fluxel.core.fluxel_status import STATUS_UI_CHOICES
from fluxel.widgets.link_friendly_text_edit import LinkFriendlyTextEdit


class TaskFormDialog(QDialog):
    """task_id が None なら新規、指定時は編集モード。"""

    def __init__(self, parent: QWidget | None = None, *, task_id: str | None = None) -> None:
        super().__init__(parent)
        self._task_id = task_id
        self._is_edit = task_id is not None
        self._deleted = False
        self.setWindowTitle("タスクの編集" if self._is_edit else "新しいタスク")

        layout = QVBoxLayout(self)

        task_layout = QHBoxLayout()
        self.label = QLabel("タスク名:", self)
        task_layout.addWidget(self.label)
        self.task_name_input = QLineEdit(self)
        task_layout.addWidget(self.task_name_input)
        layout.addLayout(task_layout)

        task_date_layout = QHBoxLayout()
        self.date_label = QLabel("完了日付:", self)
        task_date_layout.addWidget(self.date_label)
        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        task_date_layout.addWidget(self.date_edit)
        layout.addLayout(task_date_layout)

        importance_layout = QHBoxLayout()
        self.importance_label = QLabel("重要度:", self)
        importance_layout.addWidget(self.importance_label)
        self.importance_input = QComboBox(self)
        self.importance_input.addItems(["高", "中", "低"])
        importance_layout.addWidget(self.importance_input)
        layout.addLayout(importance_layout)
        if not self._is_edit:
            self.importance_input.setCurrentIndex(2)

        self.status_label = QLabel("ステータス:", self)
        self.status_input = QComboBox(self)
        for label, key in STATUS_UI_CHOICES:
            self.status_input.addItem(label, key)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.status_input)
        layout.addLayout(status_row)
        if not self._is_edit:
            self.status_label.hide()
            self.status_input.hide()

        task_description_layout = QHBoxLayout()
        self.task_description_label = QLabel("タスク説明:", self)
        task_description_layout.addWidget(self.task_description_label)

        self.task_description_input = LinkFriendlyTextEdit(self)
        self.task_description_input.setAcceptRichText(True)
        self.task_description_input.setPlaceholderText(
            "通常どおり編集できます。URL を貼るとリンク化され、"
            "取得できればページのタイトルに差し替わります。"
            "リンクはクリックでブラウザが開きます。"
        )
        self.task_description_input.setMinimumHeight(120)
        task_description_layout.addWidget(self.task_description_input)
        layout.addLayout(task_description_layout)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        if self._is_edit:
            self.delete_button = QPushButton("削除", self)
            self.delete_button.clicked.connect(self._on_delete_clicked)
            self.buttons.addButton(self.delete_button, QDialogButtonBox.ButtonRole.ActionRole)

        self._bind_ctrl_enter_accept()

        if self._is_edit:
            self._load_task_from_db(task_id or "")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)

    def was_deleted(self) -> bool:
        return self._deleted

    def _on_delete_clicked(self) -> None:
        if not self._task_id:
            return
        ans = QMessageBox.question(
            self,
            "削除の確認",
            "このタスクをデータベースから削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        conn = sqlite3.connect(TASK_DB)
        cur = conn.cursor()
        cur.execute("DELETE FROM tasks WHERE id = ?", (self._task_id,))
        conn.commit()
        conn.close()
        self._deleted = True
        self.accept()

    def _bind_ctrl_enter_accept(self) -> None:
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(
                QKeySequence(Qt.KeyboardModifier.ControlModifier | key), self
            )
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self.accept)

    def _load_task_from_db(self, task_id: str) -> None:
        conn = sqlite3.connect(TASK_DB)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, description, importance, end_date, status
            FROM tasks WHERE id = ?
            """,
            (task_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return
        name, description, importance, end_date, status = row
        self.task_name_input.setText(name or "")
        if end_date:
            self.date_edit.setDate(QDate.fromString(end_date, "yyyy-MM-dd"))
        idx = self.importance_input.findText(importance or "")
        if idx >= 0:
            self.importance_input.setCurrentIndex(idx)
        self._apply_description_from_db(description or "")
        sk = (status or "").strip().lower()
        for i in range(self.status_input.count()):
            if self.status_input.itemData(i) == sk:
                self.status_input.setCurrentIndex(i)
                break

    def _apply_description_from_db(self, raw: str) -> None:
        """DB の説明を読み込み、\\url: / \\file| および生 URL をリンク表示する。"""
        text = raw or ""
        low = text.lower()
        if "<a " in low or "<html" in low:
            self.task_description_input.setHtml(text)
            return
        self.task_description_input.setHtml(storage_to_display_html(text))
        for u in http_urls_for_title_fetch(text):
            self.task_description_input._enqueue_page_title(u)

    def get_values(self) -> tuple[str, QDate]:
        return self.task_name_input.text(), self.date_edit.date()

    def get_status_key(self) -> str:
        d = self.status_input.currentData()
        return str(d) if d is not None else "todo"

    def save_new_task(self) -> str:
        """新規タスクをDBに保存し、生成した id を返す。"""
        now = datetime.now().isoformat(timespec="seconds")
        new_id = str(uuid.uuid7())
        task_name, date = self.get_values()
        end_date = date.toString("yyyy-MM-dd")
        desc_plain = normalize_description_for_storage(
            self.task_description_input.plain_text_for_storage()
        )
        conn = sqlite3.connect(TASK_DB)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tasks (
                id, name, description, importance, created_at, update_at, end_date, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id,
                task_name,
                desc_plain,
                self.importance_input.currentText(),
                now,
                now,
                end_date,
                self.get_status_key(),
            ),
        )
        conn.commit()
        conn.close()
        return new_id

    def save_edited_task(self) -> None:
        """編集内容を DB に反映する。"""
        if not self._task_id:
            return
        now = datetime.now().isoformat(timespec="seconds")
        task_name, date = self.get_values()
        end_date = date.toString("yyyy-MM-dd")
        desc_plain = normalize_description_for_storage(
            self.task_description_input.plain_text_for_storage()
        )
        conn = sqlite3.connect(TASK_DB)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE tasks SET
                name = ?, description = ?, importance = ?, end_date = ?, status = ?,
                update_at = ?
            WHERE id = ?
            """,
            (
                task_name,
                desc_plain,
                self.importance_input.currentText(),
                end_date,
                self.get_status_key(),
                now,
                self._task_id,
            ),
        )
        conn.commit()
        conn.close()
