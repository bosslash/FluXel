"""カンバン列・カード表示・キーボード移動・DB 再読込（メイン画面のボード部分）。"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fluxel.core.fluxel_db import TASK_DB, auto_archive_stale_finish_tasks
from fluxel.core.fluxel_status import NEXT_STATUS, PREV_STATUS, STATUS_ORDER
from fluxel.core.app_settings import load_settings
from fluxel.kanban.task_card import TaskCardWidget
from fluxel.tasks.task_edit_dialog import EditTaskDialog

_log = logging.getLogger(__name__)


def _parse_task_datetime(value: str | None) -> datetime | None:
    """DB の ISO 風文字列を naive datetime に（先頭19文字まで）。"""
    s = (value or "").strip()
    if not s:
        return None
    head = s[:19].replace(" ", "T")
    try:
        return datetime.fromisoformat(head)
    except ValueError:
        return None


class KanbanBoard(QWidget):
    """カンバン列・カード・選択移動。DB は変更時のみ読み、表示はメモリキャッシュを主に使う。"""

    #: アーカイブ列に載せるのは「update_at がこの日数以内」のもののみ（古い完了は DB に残す）
    _ARCHIVE_VISIBLE_DAYS = 30

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        main_frame = QFrame(self)
        main_frame.setFrameShape(QFrame.Shape.NoFrame)
        main_frame.setStyleSheet("QFrame { border: none; background: transparent; }")
        main_outer_layout = QVBoxLayout(main_frame)

        main_scroll = QScrollArea(main_frame)
        main_scroll.setFrameShape(QFrame.Shape.NoFrame)
        main_scroll.setWidgetResizable(True)
        main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        main_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        columns_container = QWidget(main_scroll)
        columns_layout = QHBoxLayout(columns_container)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(12)

        self.column_body_layouts: dict[str, QVBoxLayout] = {}
        self.column_count_labels: dict[str, QLabel] = {}
        self.column_header_wraps: dict[str, QFrame] = {}
        self.column_cards: dict[str, list[TaskCardWidget]] = {k: [] for k in STATUS_ORDER}
        self.card_widgets: list[TaskCardWidget] = []
        self.selected_task_id: str | None = None
        self._selection_visual_card: TaskCardWidget | None = None
        self._column_focus: str | None = None
        self._column_vertical_index: int = 0
        # 列内のカード順（再起動で消える）。値は上から順の task_id リスト。
        self._manual_column_orders: dict[str, list[str]] = {}
        # SQL から読んだスナップショット（reload_db=True のとき更新）。並び替えのみならメモリ上で再計算。
        self._by_status_rows: dict[str, list[tuple]] = {k: [] for k in STATUS_ORDER}
        self._ordered_rows: list[tuple] = []
        # 1 回の再構築中に _is_dark_mode を一度だけ評価（カード大量時の微削減）
        self._palette_dark_cache: bool | None = None
        self._archive_after_days = load_settings().archive_after_days

        def make_status_column(title: str, status_key: str) -> QFrame:
            panel = QFrame(columns_container)
            panel.setFrameShape(QFrame.Shape.NoFrame)
            panel.setStyleSheet("QFrame { border: none; background: transparent; }")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(8, 6, 8, 6)
            panel_layout.setSpacing(6)

            header_wrap = QFrame(panel)
            header_wrap.setFrameShape(QFrame.Shape.NoFrame)
            header_wrap.setStyleSheet(
                "QFrame { border: none; background: transparent; }"
            )
            header_row = QHBoxLayout(header_wrap)
            header_row.setContentsMargins(6, 4, 6, 4)
            header_row.setSpacing(8)
            panel_title = QLabel(title, header_wrap)
            panel_title.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            panel_title.setStyleSheet(
                "QLabel { border: none; background: transparent; "
                "font-size: 18px; font-weight: bold; }"
            )
            header_row.addWidget(panel_title, 1)
            count_label = QLabel("0件", header_wrap)
            count_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            count_label.setStyleSheet(
                "QLabel { border: none; background: transparent; font-size: 11px; }"
            )
            header_row.addWidget(count_label)
            self.column_count_labels[status_key] = count_label
            self.column_header_wraps[status_key] = header_wrap
            panel_layout.addWidget(header_wrap)

            body_scroll = QScrollArea(panel)
            body_scroll.setFrameShape(QFrame.Shape.NoFrame)
            body_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
            body_scroll.setWidgetResizable(True)
            body_scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            body_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )

            body_container = QWidget(body_scroll)
            body_layout = QVBoxLayout(body_container)
            body_layout.setContentsMargins(2, 6, 2, 6)
            body_layout.setSpacing(8)
            body_layout.addStretch(1)
            self.column_body_layouts[status_key] = body_layout
            body_scroll.setWidget(body_container)
            panel_layout.addWidget(body_scroll, 1)

            # 固定 360×5 列だと合計幅が ~1900px を超え、FHD＋スケール時に Archive が画面外になる。
            # 最小幅のみ指定し、余白は列で均等に配分する。
            panel.setMinimumWidth(260)
            panel.setSizePolicy(
                QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding
            )
            return panel

        column_defs = (
            ("ToDo", "todo"),
            ("Doing", "doing"),
            ("Wait", "wait"),
            ("Finish", "finish"),
            ("Archive", "archive"),
        )
        first_col = True
        for title, key in column_defs:
            if not first_col:
                sep = QFrame(columns_container)
                sep.setFrameShape(QFrame.Shape.NoFrame)
                sep.setFixedWidth(1)
                sep.setStyleSheet("QFrame { background-color: #757575; border: none; }")
                sep.setSizePolicy(
                    QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
                )
                columns_layout.addWidget(sep)
            first_col = False
            columns_layout.addWidget(make_status_column(title, key), 1)

        main_scroll.setWidget(columns_container)
        main_outer_layout.addWidget(main_scroll, 1)
        outer.addWidget(main_frame, 1)

        self.refresh_task_cards(reload_db=True)

    def _importance_color(self, importance: str) -> str:
        mapping = {
            "高": "#E53935",
            "high": "#E53935",
            "中": "#1E88E5",
            "medium": "#1E88E5",
            "低": "#43A047",
            "low": "#43A047",
        }
        return mapping.get((importance or "").strip().lower(), "#9E9E9E")

    def _is_dark_mode(self) -> bool:
        base = self.palette().color(self.backgroundRole())
        return base.lightness() < 128

    def _is_dark_mode_cached(self) -> bool:
        c = self._palette_dark_cache
        if c is None:
            return self._is_dark_mode()
        return c

    def _make_task_card(
        self,
        task_id: str,
        status: str,
        task_name: str,
        end_date: str,
        importance: str,
        description: str,
    ) -> TaskCardWidget:
        desc_color = "#E8E8E8" if self._is_dark_mode_cached() else "#212121"
        title_tc = QColor("#E8E8E8") if self._is_dark_mode_cached() else QColor("#212121")
        card = TaskCardWidget(
            task_id=task_id,
            status=status,
            task_name=task_name,
            end_date=end_date,
            description_raw=description or "",
            importance_color=self._importance_color(importance),
            desc_color=desc_color,
            title_text_color=title_tc,
            parent=self,
        )
        card.clicked.connect(self._on_card_clicked)
        card.hover_entered.connect(self._on_card_hover_entered)
        return card

    def _clear_column_cards(self) -> None:
        self._selection_visual_card = None
        self.card_widgets = []
        self.column_cards = {k: [] for k in STATUS_ORDER}
        for layout in self.column_body_layouts.values():
            while layout.count() > 1:
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

    def _get_selected_card(self) -> TaskCardWidget | None:
        if self.selected_task_id is None:
            return None
        return next((c for c in self.card_widgets if c.task_id == self.selected_task_id), None)

    def _active_column_status(self) -> str | None:
        c = self._get_selected_card()
        if c is not None:
            return c.status
        return self._column_focus

    def _get_src_idx_in_column(self, status: str) -> int:
        c = self._get_selected_card()
        if c is not None and c.status == status:
            cards = self.column_cards.get(status, [])
            for i, x in enumerate(cards):
                if x.task_id == c.task_id:
                    return i
            return 0
        return self._column_vertical_index

    def _set_column_focus_only(self, status: str) -> None:
        self.selected_task_id = None
        self._column_focus = status
        prev = self._selection_visual_card
        if prev is not None:
            prev.set_selected(False)
            self._selection_visual_card = None
        self._update_empty_column_header_borders()

    def _set_selected_task(self, task_id: str | None) -> None:
        self.selected_task_id = task_id
        self._column_focus = None
        new_card: TaskCardWidget | None = None
        if task_id:
            new_card = next((c for c in self.card_widgets if c.task_id == task_id), None)
            if new_card is not None:
                cards = self.column_cards.get(new_card.status, [])
                for i, x in enumerate(cards):
                    if x.task_id == task_id:
                        self._column_vertical_index = i
                        break
        prev = self._selection_visual_card
        if prev is not None and prev is not new_card:
            prev.set_selected(False)
        self._selection_visual_card = new_card
        if new_card is not None and prev is not new_card:
            new_card.set_selected(True)
        self._update_empty_column_header_borders()
        self._scroll_selected_card_into_view()

    def _scroll_selected_card_into_view(self) -> None:
        """列内スクロールで選択カードが隠れないようにする（既に収まっていれば何もしない）。"""
        margin = 12
        c = self._get_selected_card()
        if c is None:
            return
        w: QWidget | None = c.parentWidget()
        while w is not None:
            if isinstance(w, QScrollArea):
                vp = w.viewport()
                top_left = c.mapTo(vp, QPoint(0, 0))
                card_rect = QRect(top_left, c.size())
                visible_rect = vp.rect().adjusted(margin, margin, -margin, -margin)
                if visible_rect.contains(card_rect):
                    return
                w.ensureWidgetVisible(c, margin, margin)
                return
            w = w.parentWidget()

    def _on_card_hover_entered(self, task_id: str) -> None:
        # Ctrl+↑/↓ で並び替えた直後、マウス直下のカードが入れ替わり Enter が連発し、
        # 選択がマウス位置に固定されて「同じところで入れ替わるだけ」に見えるのを防ぐ。
        if QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._set_selected_task(task_id)

    def _on_card_clicked(self, task_id: str) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self.selected_task_id == task_id:
            self._open_task_edit_dialog(task_id)
            return
        self._set_selected_task(task_id)

    def _move_selection_vertical(self, step: int) -> None:
        if not self.card_widgets and self._column_focus is None:
            return
        current = self._get_selected_card()
        if current is None:
            col = self._column_focus
            if col is None:
                if self.card_widgets:
                    self._set_selected_task(self.card_widgets[0].task_id)
                return
            cards = self.column_cards.get(col, [])
            if not cards:
                return
            idx = min(max(0, self._column_vertical_index), len(cards) - 1)
            new_idx = max(0, min(len(cards) - 1, idx + step))
            self._column_vertical_index = new_idx
            self._set_selected_task(cards[new_idx].task_id)
            return
        cards = self.column_cards.get(current.status, [])
        if not cards:
            return
        idx = next((i for i, c in enumerate(cards) if c.task_id == current.task_id), 0)
        next_idx = max(0, min(len(cards) - 1, idx + step))
        self._column_vertical_index = next_idx
        self._set_selected_task(cards[next_idx].task_id)

    def _move_selection_horizontal(self, step: int) -> None:
        col = self._active_column_status()
        if col is None or col not in STATUS_ORDER:
            if self.card_widgets:
                self._set_selected_task(self.card_widgets[0].task_id)
            elif STATUS_ORDER:
                self._set_column_focus_only(STATUS_ORDER[0])
            return
        src_idx = self._get_src_idx_in_column(col)
        ci = STATUS_ORDER.index(col)
        ni = ci + step
        if ni < 0 or ni >= len(STATUS_ORDER):
            return
        target_status = STATUS_ORDER[ni]
        target_cards = self.column_cards.get(target_status, [])
        if target_cards:
            target_idx = min(max(0, src_idx), len(target_cards) - 1)
            self._column_vertical_index = target_idx
            self._set_selected_task(target_cards[target_idx].task_id)
        else:
            self._column_vertical_index = src_idx
            self._set_column_focus_only(target_status)

    def _move_selected_task_status(self, direction: int) -> None:
        card = self._get_selected_card()
        if card is None:
            return
        current = card.status
        next_status = NEXT_STATUS.get(current) if direction > 0 else PREV_STATUS.get(current)
        if next_status is None:
            return

        now = datetime.now().isoformat(timespec="seconds")
        conn = sqlite3.connect(TASK_DB)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET status = ?, update_at = ? WHERE id = ?",
            (next_status, now, card.task_id),
        )
        conn.commit()
        conn.close()

        _log.debug(
            "status change id=%s %s -> %s at %s",
            card.task_id,
            current,
            next_status,
            now,
        )

        self.selected_task_id = card.task_id
        self._load_rows_from_sql()
        if not self._relayout_widgets_after_sql_preserving_cards():
            self._rebuild_widgets_from_ordered_rows()

    def _open_task_edit_dialog(self, task_id: str) -> None:
        top = self.window()
        dialog = EditTaskDialog(top, task_id=task_id)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            _log.debug("task edit cancelled id=%s", task_id)
            return
        if dialog.was_deleted():
            ts = datetime.now().isoformat(timespec="seconds")
            _log.debug("task deleted id=%s at %s", task_id, ts)
            if self.selected_task_id == task_id:
                self.selected_task_id = None
            self.refresh_task_cards(reload_db=True)
            return
        dialog.save_edited_task()
        ts = datetime.now().isoformat(timespec="seconds")
        task_name, date = dialog.get_values()
        _log.debug(
            "task saved id=%s name=%r end_date=%s importance=%r status=%s at %s",
            task_id,
            task_name,
            date.toString("yyyy-MM-dd"),
            dialog.importance_input.currentText(),
            dialog.get_status_key(),
            ts,
        )
        self.selected_task_id = task_id
        self.refresh_task_cards(reload_db=True)

    def on_selected_card_enter(self, card: TaskCardWidget) -> None:
        self._open_task_edit_dialog(card.task_id)

    def _trigger_selected_card(self) -> None:
        if self.selected_task_id is None:
            return
        card = next((c for c in self.card_widgets if c.task_id == self.selected_task_id), None)
        if card is None:
            return
        self.on_selected_card_enter(card)

    def reorder_selected_card(self, delta: int) -> None:
        """同一列内で Ctrl+↑/↓ による並び替え（メモリのみ。再起動で既定順に戻る）。"""
        if delta not in (-1, 1):
            return
        card = self._get_selected_card()
        if card is None:
            return
        status = card.status
        cards = list(self.column_cards.get(status, []))
        if len(cards) < 2:
            return
        try:
            idx = next(i for i, c in enumerate(cards) if c.task_id == card.task_id)
        except StopIteration:
            return
        j = idx + delta
        if j < 0 or j >= len(cards):
            return
        cards[idx], cards[j] = cards[j], cards[idx]
        self._manual_column_orders[status] = [c.task_id for c in cards]
        self.refresh_task_cards(reload_db=False)

    def _update_empty_column_header_borders(self) -> None:
        """カード 0 件でその列だけがフォーカスされているとき、ヘッダに枠線を出す。"""
        focused_style = (
            "QFrame { border: 1px solid #757575; border-radius: 4px; "
            "background: transparent; }"
        )
        normal_style = "QFrame { border: none; background: transparent; }"
        for key, wrap in self.column_header_wraps.items():
            n = len(self.column_cards.get(key, []))
            show = (
                n == 0
                and self._column_focus == key
                and self.selected_task_id is None
            )
            wrap.setStyleSheet(focused_style if show else normal_style)

    @staticmethod
    def _row_sort_key(r: tuple) -> tuple:
        _, _, _, end_date, _, _ = r
        ed = (end_date or "").strip()
        if not ed:
            return (1, "", r[0] or "")
        head = ed[:10].replace("/", "-")
        return (0, head, r[0] or "")

    def _prune_manual_orders(self) -> None:
        for key in list(self._manual_column_orders.keys()):
            ids_here = {r[0] for r in self._by_status_rows.get(key, []) if r[0]}
            pruned = [tid for tid in self._manual_column_orders[key] if tid in ids_here]
            if pruned:
                self._manual_column_orders[key] = pruned
            else:
                del self._manual_column_orders[key]

    def _recompute_ordered_rows(self) -> None:
        ordered_flat: list[tuple] = []
        for key in STATUS_ORDER:
            lst = list(self._by_status_rows.get(key, []))
            lst.sort(key=self._row_sort_key)
            manual = self._manual_column_orders.get(key)
            if manual:
                id_to_row = {r[0]: r for r in lst if r[0]}
                seen: set[str] = set()
                merged: list[tuple] = []
                for tid in manual:
                    if tid in id_to_row:
                        merged.append(id_to_row[tid])
                        seen.add(tid)
                rest = [r for r in lst if (r[0] or "") not in seen]
                rest.sort(key=self._row_sort_key)
                merged.extend(rest)
                lst = merged
            ordered_flat.extend(lst)
        self._ordered_rows = ordered_flat

    def _relayout_widgets_after_sql_preserving_cards(self) -> bool:
        """DB 再読込後、表示タスク集合が変わらないときだけ全カード再生成を避けて列を付け替える。"""
        desired = self._desired_column_task_ids()
        flat_desired: list[str] = []
        for k in STATUS_ORDER:
            flat_desired.extend(desired[k])
        want: set[str] = set(flat_desired)
        if len(flat_desired) != len(want):
            return False
        id_to_card: dict[str, TaskCardWidget] = {}
        for c in self.card_widgets:
            tid = c.task_id or ""
            if not tid or tid in id_to_card:
                return False
            id_to_card[tid] = c
        if want != set(id_to_card.keys()):
            return False
        if len(self.card_widgets) != len(id_to_card):
            return False
        for tid in flat_desired:
            if tid not in id_to_card:
                return False

        for key in STATUS_ORDER:
            layout = self.column_body_layouts[key]
            while layout.count() > 1:
                layout.takeAt(0)
        for key in STATUS_ORDER:
            layout = self.column_body_layouts[key]
            col_cards: list[TaskCardWidget] = []
            for tid in desired[key]:
                card = id_to_card[tid]
                card.status = key
                layout.insertWidget(max(layout.count() - 1, 0), card)
                col_cards.append(card)
            self.column_cards[key] = col_cards
        self.card_widgets = [id_to_card[tid] for tid in flat_desired]
        self._sync_column_header_counts()
        self._restore_selection_state()
        return True

    def _load_rows_from_sql(self) -> None:
        auto_archive_stale_finish_tasks(days=self._archive_after_days)
        conn = sqlite3.connect(TASK_DB)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, description, end_date, status, importance, update_at
            FROM tasks
            ORDER BY
                CASE lower(status)
                    WHEN 'todo' THEN 1
                    WHEN 'doing' THEN 2
                    WHEN 'wait' THEN 3
                    WHEN 'finish' THEN 4
                    WHEN 'archive' THEN 5
                    ELSE 99
                END,
                CASE WHEN end_date IS NULL OR trim(COALESCE(end_date, '')) = ''
                    THEN 1 ELSE 0 END,
                end_date ASC,
                created_at DESC
            """
        )
        rows = cursor.fetchall()
        conn.close()

        archive_cutoff = datetime.now() - timedelta(days=self._ARCHIVE_VISIBLE_DAYS)
        by_status: dict[str, list[tuple]] = {k: [] for k in STATUS_ORDER}
        for task_id, name, description, end_date, status, importance, update_at in rows:
            key = (status or "").strip().lower()
            if key == "archive":
                ua_dt = _parse_task_datetime(update_at)
                if ua_dt is not None and ua_dt < archive_cutoff:
                    continue
            if key in by_status:
                by_status[key].append(
                    (task_id, name, description, end_date, status, importance)
                )
        self._by_status_rows = by_status
        self._prune_manual_orders()
        self._recompute_ordered_rows()

    def _desired_column_task_ids(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {k: [] for k in STATUS_ORDER}
        for row in self._ordered_rows:
            st = (row[4] or "").strip().lower()
            tid = row[0] or ""
            if st in out:
                out[st].append(tid)
        return out

    def _column_orders_match_visual(self, desired: dict[str, list[str]]) -> bool:
        for k in STATUS_ORDER:
            cur = [c.task_id for c in self.column_cards.get(k, [])]
            if cur != desired.get(k, []):
                return False
        return True

    def _can_reorder_layout_only(self, desired: dict[str, list[str]]) -> bool:
        if not self.card_widgets:
            return False
        for k in STATUS_ORDER:
            cur = [c.task_id for c in self.column_cards.get(k, [])]
            tgt = desired.get(k, [])
            if len(cur) != len(tgt) or sorted(cur) != sorted(tgt):
                return False
        return True

    def _reorder_column_layout_inplace(self, status_key: str, desired_ids: list[str]) -> None:
        layout = self.column_body_layouts[status_key]
        id_to_card = {c.task_id: c for c in self.column_cards.get(status_key, [])}
        # 末尾の stretch 以外をすべて外す（ウィジェットは deleteLater しない）
        while layout.count() > 1:
            layout.takeAt(0)
        for tid in desired_ids:
            card = id_to_card.get(tid)
            if card is None:
                continue
            layout.insertWidget(max(layout.count() - 1, 0), card)
        self.column_cards[status_key] = [id_to_card[tid] for tid in desired_ids if tid in id_to_card]

    def _rebuild_via_layout_reorder_only(self) -> bool:
        """同一タスク集合で順序だけ変わったとき、deleteLater せずレイアウト差し替えのみ。"""
        desired = self._desired_column_task_ids()
        if self._column_orders_match_visual(desired):
            return True
        if not self._can_reorder_layout_only(desired):
            return False
        for k in STATUS_ORDER:
            self._reorder_column_layout_inplace(k, desired[k])
        self.card_widgets = [c for k in STATUS_ORDER for c in self.column_cards.get(k, [])]
        self._sync_column_header_counts()
        self._restore_selection_state()
        return True

    def _sync_column_header_counts(self) -> None:
        for key in STATUS_ORDER:
            n = len(self.column_cards.get(key, []))
            label = self.column_count_labels.get(key)
            if label is not None:
                label.setText(f"{n}件")

    def _restore_selection_state(self) -> None:
        if not self.card_widgets:
            self.selected_task_id = None
            self._column_focus = None
            self._update_empty_column_header_borders()
            return
        if self.selected_task_id and any(
            c.task_id == self.selected_task_id for c in self.card_widgets
        ):
            self._set_selected_task(self.selected_task_id)
        elif self._column_focus in STATUS_ORDER:
            cards = self.column_cards.get(self._column_focus, [])
            if cards:
                idx = min(max(0, self._column_vertical_index), len(cards) - 1)
                self._set_selected_task(cards[idx].task_id)
            else:
                self._set_column_focus_only(self._column_focus)
        else:
            self._set_selected_task(self.card_widgets[0].task_id)

    def _rebuild_widgets_from_ordered_rows(self) -> None:
        self._palette_dark_cache = self._is_dark_mode()
        col_layouts = list(self.column_body_layouts.values())
        for ly in col_layouts:
            ly.setEnabled(False)
        self.setUpdatesEnabled(False)
        try:
            self._clear_column_cards()
            for task_id, name, description, end_date, status, importance in self._ordered_rows:
                key = (status or "").strip().lower()
                layout = self.column_body_layouts.get(key)
                if layout is None:
                    continue
                card = self._make_task_card(
                    task_id=task_id or "",
                    status=key,
                    task_name=name or "",
                    end_date=end_date or "",
                    importance=importance or "",
                    description=description or "",
                )
                insert_index = max(layout.count() - 1, 0)
                layout.insertWidget(insert_index, card)
                self.card_widgets.append(card)
                self.column_cards.setdefault(key, []).append(card)
        finally:
            for ly in col_layouts:
                ly.setEnabled(True)
            self.setUpdatesEnabled(True)

        self._sync_column_header_counts()

        self._palette_dark_cache = None

        self._restore_selection_state()

    def refresh_task_cards(self, *, reload_db: bool = True) -> None:
        """
        reload_db=True: SQLite から全行読み、メモリキャッシュ更新後にウィジェット再構築。
        reload_db=False: メモリ上の _by_status_rows のみで表示順を再計算（Ctrl+↑/↓ 並び替え用）。
        """
        if reload_db:
            self._load_rows_from_sql()
            self._rebuild_widgets_from_ordered_rows()
        else:
            self._recompute_ordered_rows()
            if not self._rebuild_via_layout_reorder_only():
                self._rebuild_widgets_from_ordered_rows()

    def set_selected_task_id(self, task_id: str | None) -> None:
        """親ウィンドウから新規作成直後などに選択 ID を指定する。"""
        self.selected_task_id = task_id

    def set_archive_after_days(self, days: int) -> None:
        self._archive_after_days = max(int(days), 1)
