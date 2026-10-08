"""新規タスク追加ウィンドウ（task_id なしの TaskFormDialog）。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from fluxel.tasks.task_dialog_common import TaskFormDialog


class NewTaskDialog(TaskFormDialog):
    """新しいタスク用ダイアログ。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_status: str = "todo",
    ) -> None:
        super().__init__(parent, task_id=None)
        status_index = self.status_input.findData(
            (initial_status or "todo").strip().lower()
        )
        self.status_input.setCurrentIndex(
            status_index if status_index >= 0 else 0
        )
