"""QuickAccessタグの選択・追加・削除を一貫して扱うダイアログ。"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fluxel.core.quick_access_db import (
    add_known_tag,
    delete_known_tag,
    list_known_tags,
)


def split_tags(raw: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in re.split(r"[,、\n]+", raw or ""):
        tag = value.strip()
        key = tag.lower()
        if not tag or key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return result


class TagPickerDialog(QDialog):
    def __init__(
        self,
        initial_tags: str = "",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("タグを選択")
        self.setMinimumSize(420, 420)
        self._checked = {tag.lower() for tag in split_tags(initial_tags)}
        root = QVBoxLayout(self)
        help_label = QLabel(
            "使用するタグをチェックしてください。新しいタグは下から追加できます。",
            self,
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("QLabel { color:#6B7280; }")
        root.addWidget(help_label)
        self._list = QListWidget(self)
        root.addWidget(self._list, 1)
        add_row = QHBoxLayout()
        self._input = QLineEdit(self)
        self._input.setPlaceholderText("新しいタグ（複数はカンマ区切り）")
        add_button = QPushButton("追加して選択", self)
        add_button.clicked.connect(self._add)
        self._input.returnPressed.connect(self._add)
        add_row.addWidget(self._input, 1)
        add_row.addWidget(add_button)
        root.addLayout(add_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._reload()

    def selected_tags(self) -> str:
        selected: list[str] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())
        return ", ".join(selected)

    def _reload(self) -> None:
        self._list.clear()
        for tag in list_known_tags():
            item = QListWidgetItem(tag, self._list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if tag.lower() in self._checked
                else Qt.CheckState.Unchecked
            )

    def _add(self) -> None:
        tags = split_tags(self._input.text())
        if not tags:
            return
        add_known_tag(", ".join(tags))
        self._checked.update(tag.lower() for tag in tags)
        self._input.clear()
        self._reload()


class TagManagerDialog(QDialog):
    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("タグ管理")
        self.setMinimumSize(460, 440)
        root = QVBoxLayout(self)
        help_label = QLabel(
            "タグの追加と削除をここで行います。削除すると保存項目からもタグが外れます。",
            self,
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("QLabel { color:#6B7280; }")
        root.addWidget(help_label)
        self._list = QListWidget(self)
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        root.addWidget(self._list, 1)
        add_row = QHBoxLayout()
        self._input = QLineEdit(self)
        self._input.setPlaceholderText("追加するタグ（複数はカンマ区切り）")
        add_button = QPushButton("追加", self)
        add_button.clicked.connect(self._add)
        self._input.returnPressed.connect(self._add)
        add_row.addWidget(self._input, 1)
        add_row.addWidget(add_button)
        root.addLayout(add_row)
        action_row = QHBoxLayout()
        self._status = QLabel("", self)
        self._status.setStyleSheet("QLabel { color:#6B7280; }")
        delete_button = QPushButton("選択タグを削除", self)
        delete_button.clicked.connect(self._delete)
        action_row.addWidget(self._status, 1)
        action_row.addWidget(delete_button)
        root.addLayout(action_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close, parent=self
        )
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        root.addWidget(buttons)
        self._reload()

    def _reload(self, select: set[str] | None = None) -> None:
        select = {value.lower() for value in (select or set())}
        self._list.clear()
        for tag in list_known_tags():
            item = QListWidgetItem(tag, self._list)
            item.setSelected(tag.lower() in select)
        self._status.setText(f"{self._list.count()}件")

    def _add(self) -> None:
        tags = split_tags(self._input.text())
        if not tags:
            self._status.setText("追加するタグを入力してください。")
            return
        add_known_tag(", ".join(tags))
        self._input.clear()
        self._reload(set(tags))
        self._status.setText(f"{len(tags)}件追加しました。")

    def _delete(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            self._status.setText("削除するタグを選択してください。")
            return
        names = [item.text() for item in selected]
        answer = QMessageBox.question(
            self,
            "タグを削除",
            f"{len(names)}件のタグを削除しますか？\n保存項目からもタグが外れます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for name in names:
            delete_known_tag(name)
        self._reload()
        self._status.setText(f"{len(names)}件削除しました。")
