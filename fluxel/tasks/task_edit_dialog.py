"""既存タスク編集ウィンドウ（ステータス・削除あり）。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from fluxel.tasks.task_dialog_common import TaskFormDialog


class EditTaskDialog(TaskFormDialog):
    """既存タスクの編集・削除用ダイアログ。"""

    def __init__(self, parent: QWidget | None, *, task_id: str) -> None:
        super().__init__(parent, task_id=task_id)
