"""ShortCut/OpenFile 共通の検索＋管理 UI。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QTimer, Qt, Signal, QStringListModel
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QGridLayout,
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


class _SearchLineEdit(QLineEdit):
    """検索欄専用。フォーカス時の不要な選択描画を抑制する。"""

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.deselect()
        self.setCursorPosition(len(self.text()))

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self.deselect()


class QuickAccessPanel(QWidget):
    """タイトル・タグ検索、項目追加、結果選択/実行の共通パネル。"""

    execute_item = Signal(str, str, str, str)  # id, title, value, tags
    manage_tags_requested = Signal()
    edit_tags_requested = Signal(object)  # 対象QLineEdit

    def __init__(
        self,
        *,
        title: str,
        value_label: str,
        add_label: str,
        execute_label: str,
        show_editor: bool = True,
        on_search: Callable[[str, str], list[tuple]],
        on_add: Callable[[str, str, str], str],
        on_update: Callable[[str, str, str, str], None],
        on_delete: Callable[[str], None],
        tag_candidates_getter: Callable[[], list[str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_search = on_search
        self._on_add = on_add
        self._on_update = on_update
        self._on_delete = on_delete
        self._tag_candidates_getter = tag_candidates_getter or (lambda: [])
        self._show_editor = show_editor
        self._last_loaded_query = ""
        self._last_loaded_tag_query = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        if (title or "").strip():
            hdr = QLabel(title, self)
            hdr.setStyleSheet("QLabel { font-size: 16px; font-weight: bold; }")
            root.addWidget(hdr)

        filter_row = QHBoxLayout()
        self._query = _SearchLineEdit(self)
        self._query.setPlaceholderText(f"名前・{value_label}・タグを検索")
        self._query.setAccessibleName(f"名前・{value_label}・タグを検索")
        self._query.setToolTip("入力すると自動で絞り込みます。/ で検索欄へ移動")
        self._query.setClearButtonEnabled(True)
        self._tag_query = _SearchLineEdit(self)
        self._tag_query.setPlaceholderText("タグで絞り込み")
        self._tag_query.setAccessibleName("タグで絞り込み")
        self._tag_query.setToolTip("カンマ区切りで複数タグを指定できます")
        self._tag_query.setClearButtonEnabled(True)
        line_style = (
            "QLineEdit {"
            " background-color: #2d2d2d;"
            " color: #e8e8e8;"
            " border: 1px solid #555555;"
            " border-radius: 6px;"
            " padding: 6px 8px;"
            " selection-background-color: transparent;"
            " selection-color: #ffffff;"
            " outline: none;"
            "}"
            "QLineEdit:focus {"
            " background-color: #2d2d2d;"
            " border: 1px solid #5c9ccc;"
            "}"
        )
        self._query.setStyleSheet(line_style)
        self._tag_query.setStyleSheet(line_style)
        self._query.setInputMethodHints(Qt.InputMethodHint.ImhNone)
        self._tag_query.setInputMethodHints(Qt.InputMethodHint.ImhNone)
        btn_manage_tags = QPushButton("タグ管理", self)
        btn_manage_tags.setToolTip("タグを追加・削除します")
        btn_manage_tags.clicked.connect(self.manage_tags_requested)
        btn_filter = QPushButton("絞り込む", self)
        btn_filter.setToolTip("Enter でも絞り込めます")
        btn_filter.clicked.connect(self.reload)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.reload)
        self._query.textChanged.connect(self._schedule_reload)
        self._tag_query.textChanged.connect(self._schedule_reload)
        self._query.returnPressed.connect(self._on_search_enter)
        self._tag_query.returnPressed.connect(self._on_search_enter)
        self._query.installEventFilter(self)
        self._tag_query.installEventFilter(self)
        self._tag_model = QStringListModel([], self)
        self._tag_completer = QCompleter(self._tag_model, self)
        self._tag_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._tag_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._tag_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._tag_query.setCompleter(self._tag_completer)
        self._tag_query.textEdited.connect(self._refresh_tag_completion)
        self._tag_completer.activated[str].connect(self._apply_tag_completion)
        filter_row.addWidget(self._query, 2)
        filter_row.addWidget(self._tag_query, 1)
        filter_row.addWidget(btn_manage_tags)
        filter_row.addWidget(btn_filter)
        root.addLayout(filter_row)
        self._summary = QLabel("", self)
        self._summary.setStyleSheet(
            "QLabel { color: #9ca3af; font-size: 11px; padding: 0 2px; }"
        )
        root.addWidget(self._summary)

        self._title: QLineEdit | None = None
        self._value: QLineEdit | None = None
        self._tags: QLineEdit | None = None
        if self._show_editor:
            self._title = QLineEdit(self)
            self._title.setPlaceholderText("表示名")
            self._value = QLineEdit(self)
            self._value.setPlaceholderText(value_label)
            self._tags = QLineEdit(self)
            self._tags.setPlaceholderText("タグ（カンマ区切り・任意）")
            form_frame = QFrame(self)
            form_lay = QGridLayout(form_frame)
            form_lay.setContentsMargins(0, 0, 0, 0)
            form_lay.setHorizontalSpacing(8)
            form_lay.setVerticalSpacing(6)
            form_lay.addWidget(QLabel("タイトル", self), 0, 0)
            form_lay.addWidget(self._title, 0, 1)
            form_lay.addWidget(QLabel(value_label, self), 1, 0)
            form_lay.addWidget(self._value, 1, 1)
            form_lay.addWidget(QLabel("タグ", self), 2, 0)
            form_lay.addWidget(self._tags, 2, 1)
            btn_pick_tags = QPushButton("選択…", self)
            btn_pick_tags.setToolTip("候補から選択、または新しいタグを追加")
            btn_pick_tags.clicked.connect(
                lambda: self.edit_tags_requested.emit(self._tags)
            )
            form_lay.addWidget(btn_pick_tags, 2, 2)
            editor_label = QLabel("選択中の項目を編集", self)
            editor_label.setStyleSheet(
                "QLabel { color: #9ca3af; font-size: 11px; padding-top: 4px; }"
            )
            root.addWidget(editor_label)
            root.addWidget(form_frame)

        btn_row = QHBoxLayout()
        if self._show_editor:
            self._btn_edit = QPushButton("選択項目を更新", self)
            self._btn_delete = QPushButton("選択項目を削除", self)
            self._btn_edit.clicked.connect(self._update_selected)
            self._btn_delete.clicked.connect(self._delete_selected)
            btn_row.addWidget(self._btn_edit)
            btn_row.addWidget(self._btn_delete)
        self._btn_exec = QPushButton(execute_label, self)
        self._btn_exec.clicked.connect(self._emit_execute_selected)
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_exec)
        root.addLayout(btn_row)

        self._list = QListWidget(self)
        self._list.itemSelectionChanged.connect(self._fill_form_from_selected)
        self._list.itemDoubleClicked.connect(lambda _item: self._emit_execute_selected())
        root.addWidget(self._list, 1)

    def _schedule_reload(self) -> None:
        self._search_timer.start()

    def reload(self) -> None:
        self._search_timer.stop()
        q = self._query.text().strip()
        t = self._tag_query.text().strip()
        self._last_loaded_query = q
        self._last_loaded_tag_query = t
        rows = self._on_search(q, t)
        self._list.clear()
        filtering = bool(q or t)
        if filtering:
            self._summary.setText(f"{len(rows)}件  ·  ↑↓で選択 / Enterで実行")
        else:
            self._summary.setText(
                f"保存済み {len(rows)}件  ·  よく使う順 / 最近使った順"
            )
        for item_id, title, value, tags, use_count, _updated in rows:
            tag_text = f"  ·  #{tags.replace(',', '  #')}" if tags else ""
            used_text = f"  ·  {use_count}回使用" if use_count else ""
            text = f"{title}{tag_text}{used_text}\n{value}"
            it = QListWidgetItem(text, self._list)
            it.setToolTip(value)
            it.setData(Qt.ItemDataRole.UserRole, (item_id, title, value, tags or ""))
            self._list.addItem(it)
        if rows:
            self._list.setCurrentRow(0)
        else:
            hint = (
                "一致する項目はありません。検索語やタグを減らしてみてください。"
                if filtering
                else "まだ保存されていません。上の追加ボタンから最初の項目を保存できます。"
            )
            empty = QListWidgetItem(hint, self._list)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)

    def select_item(self, item_id: str) -> bool:
        for row in range(self._list.count()):
            item = self._list.item(row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and str(data[0]) == item_id:
                self._list.setCurrentRow(row)
                self._list.scrollToItem(item)
                return True
        return False

    def focus_search(self) -> None:
        self._query.setFocus()
        self._query.setCursorPosition(len(self._query.text()))

    def set_value(self, title: str, value: str, tags: str = "") -> None:
        if self._title is None or self._value is None or self._tags is None:
            return
        self._title.setText(title)
        self._value.setText(value)
        self._tags.setText(tags)

    def execute_selected(self) -> None:
        self._emit_execute_selected()

    def move_selection(self, delta: int) -> bool:
        n = self._list.count()
        if n <= 0:
            return False
        cur = self._list.currentRow()
        if cur < 0:
            cur = 0
        nxt = max(0, min(n - 1, cur + delta))
        self._list.setCurrentRow(nxt)
        item = self._list.item(nxt)
        if item is not None:
            self._list.scrollToItem(item)
        return True

    def _on_search_enter(self) -> None:
        q = self._query.text().strip()
        t = self._tag_query.text().strip()
        if q != self._last_loaded_query or t != self._last_loaded_tag_query:
            self.reload()
            return
        self._emit_execute_selected()

    def handle_enter(self) -> None:
        self._on_search_enter()

    def _current_tag_prefix(self) -> str:
        text = self._tag_query.text()
        i = text.rfind(",")
        return text[i + 1 :].strip()

    def _refresh_tag_completion(self) -> None:
        prefix = self._current_tag_prefix().lower()
        if not prefix:
            self._tag_completer.popup().hide()
            self._tag_model.setStringList([])
            return
        tags = self._tag_candidates_getter()
        tags = [t for t in tags if prefix in t.lower()]
        self._tag_model.setStringList(tags[:80])
        if tags:
            self._tag_completer.complete()
            pop = self._tag_completer.popup()
            if pop.model() is not None and pop.model().rowCount() > 0:
                pop.setCurrentIndex(pop.model().index(0, 0))

    def _apply_tag_completion(self, selected: str) -> None:
        text = self._tag_query.text()
        i = text.rfind(",")
        base = text[: i + 1] if i >= 0 else ""
        if base and not base.endswith((" ", ",")):
            base = base + " "
        self._tag_query.setText(f"{base}{selected}, ")

    def _move_tag_completion(self, delta: int) -> bool:
        pop = self._tag_completer.popup()
        if pop is None or not pop.isVisible() or pop.model() is None:
            return False
        n = pop.model().rowCount()
        if n <= 0:
            return False
        cur = pop.currentIndex().row()
        if cur < 0:
            cur = 0
        nxt = max(0, min(n - 1, cur + delta))
        pop.setCurrentIndex(pop.model().index(nxt, 0))
        return True

    def _delete_prev_tag_token(self, line: QLineEdit) -> bool:
        text = line.text()
        if not text:
            return False
        cur = line.cursorPosition()
        if cur <= 0:
            return False
        left = text[:cur].rstrip(" ,")
        if not left:
            line.setText(text[cur:])
            line.setCursorPosition(0)
            return True
        cut = left.rfind(",")
        new_left = left[: cut + 1] if cut >= 0 else ""
        if new_left and not new_left.endswith(" "):
            new_left += " "
        new_text = new_left + text[cur:]
        line.setText(new_text)
        line.setCursorPosition(len(new_left))
        return True

    def _selected_data(self) -> tuple[str, str, str, str] | None:
        it = self._list.currentItem()
        if it is None:
            return None
        data = it.data(Qt.ItemDataRole.UserRole)
        return tuple(data) if data is not None else None

    def _fill_form_from_selected(self) -> None:
        if not self._show_editor:
            return
        data = self._selected_data()
        if data is None:
            return
        _id, title, value, tags = data
        if self._title is None or self._value is None or self._tags is None:
            return
        self._title.setText(title)
        self._value.setText(value)
        self._tags.setText(tags)

    def _add_or_update(self) -> None:
        if self._title is None or self._value is None or self._tags is None:
            return
        title = self._title.text().strip()
        value = self._value.text().strip()
        tags = self._tags.text().strip()
        if not title or not value:
            self._summary.setText("表示名と内容を入力してください。")
            return
        item_id = self._on_add(title, value, tags)
        self.reload()
        self.select_item(item_id)
        self._summary.setText("保存しました。Enterですぐ実行できます。")

    def _update_selected(self) -> None:
        if self._title is None or self._value is None or self._tags is None:
            return
        data = self._selected_data()
        if data is None:
            return
        item_id, _old_title, _old_value, _old_tags = data
        title = self._title.text().strip()
        value = self._value.text().strip()
        tags = self._tags.text().strip()
        if not title or not value:
            return
        self._on_update(item_id, title, value, tags)
        self.reload()
        self.select_item(item_id)
        self._summary.setText("更新しました。")

    def _delete_selected(self) -> None:
        data = self._selected_data()
        if data is None:
            return
        item_id, title, _value, _tags = data
        answer = QMessageBox.question(
            self,
            "保存項目を削除",
            f"「{title}」を削除しますか？\nこの操作は元に戻せません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._on_delete(item_id)
        self.reload()
        self._summary.setText("削除しました。")

    def _emit_execute_selected(self) -> None:
        data = self._selected_data()
        if data is None:
            return
        item_id, title, value, tags = data
        self.execute_item.emit(item_id, title, value, tags)

    def eventFilter(self, obj, event) -> bool:
        if obj in (self._query, self._tag_query) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                if self._list.count() > 0:
                    self._list.setFocus()
                else:
                    self.setFocus()
                event.accept()
                return True
            if obj is self._tag_query and key == Qt.Key.Key_Backspace:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if self._delete_prev_tag_token(self._tag_query):
                        event.accept()
                        return True
                # 区切り直後は通常 Backspace でもトークン単位削除を優先
                cur = self._tag_query.cursorPosition()
                left = self._tag_query.text()[:cur]
                if left.endswith(",") or left.endswith(", "):
                    if self._delete_prev_tag_token(self._tag_query):
                        event.accept()
                        return True
            if key == Qt.Key.Key_Up:
                if self._move_tag_completion(-1):
                    event.accept()
                    return True
                if self.move_selection(-1):
                    event.accept()
                    return True
            if key == Qt.Key.Key_Down:
                if self._move_tag_completion(1):
                    event.accept()
                    return True
                if self.move_selection(1):
                    event.accept()
                    return True
        return super().eventFilter(obj, event)


class QuickAccessPopup(QFrame):
    """QuickAccessPanel をホバー表示するフローティングポップアップ。"""

    def __init__(
        self,
        *,
        title: str,
        value_label: str,
        add_label: str,
        execute_label: str,
        on_search: Callable[[str, str], list[tuple]],
        on_add: Callable[[str, str, str], str],
        on_update: Callable[[str, str, str, str], None],
        on_delete: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("QuickAccessPopup")
        self.setStyleSheet(
            "#QuickAccessPopup { background-color: #2d2d2d; border: 1px solid #555555; border-radius: 8px; }"
        )
        self.setMinimumWidth(520)
        self.setMaximumWidth(680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.panel = QuickAccessPanel(
            title=title,
            value_label=value_label,
            add_label=add_label,
            execute_label=execute_label,
            on_search=on_search,
            on_add=on_add,
            on_update=on_update,
            on_delete=on_delete,
            parent=self,
        )
        lay.addWidget(self.panel)

    def show_near_anchor(self, anchor: QWidget) -> None:
        scr = anchor.screen()
        ag = scr.availableGeometry() if scr is not None else QGuiApplication.primaryScreen().availableGeometry()
        self.show()
        self.adjustSize()
        w = min(max(self.sizeHint().width(), self.minimumWidth()), self.maximumWidth())
        h = min(self.sizeHint().height(), ag.height() - 24)
        self.resize(w, h)
        gp = anchor.mapToGlobal(anchor.rect().bottomLeft())
        x = gp.x()
        y = gp.y() - 2
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
        self.panel.reload()
