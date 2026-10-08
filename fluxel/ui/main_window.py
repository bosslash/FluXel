"""メインウィンドウ: ヘッダナビ・カンバン／ショートカット／ファイル・グローバルショートカット。"""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Qt, QUrl, QStringListModel
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QLineEdit,
    QListWidget,
    QSpinBox,
    QScrollArea,
    QStackedWidget,
    QCompleter,
    QVBoxLayout,
    QWidget,
)

from fluxel.__about__ import APP_NAME, APP_VERSION
from fluxel.core.app_settings import AppSettings, load_settings, save_settings, settings_ini_path
from fluxel.core.dbsync import (
    SyncBusyError,
    SyncTargetError,
    discover_onedrive_candidates,
    inspect_sync_target,
    sync_folder,
)
from fluxel.core.fluxel_db import TASK_DB, ensure_tasks_table
from fluxel.core.quick_access_db import (
    add_openfile_item,
    add_shortcut_item,
    add_known_tag,
    bump_openfile_use_count,
    bump_shortcut_use_count,
    delete_known_tag,
    delete_openfile_item,
    delete_shortcut_item,
    list_known_tags,
    search_openfile_items,
    search_shortcut_items,
    update_openfile_item,
    update_shortcut_item,
    ensure_quick_access_tables,
)
from fluxel.core.gantt_db import ensure_gantt_tables
from fluxel.core.storage_manager import (
    StorageMoveError,
    database_paths,
    find_uninstaller,
    is_onedrive_path,
    move_database_directory,
    move_settings_file,
)
from fluxel.kanban.board import KanbanBoard
from fluxel.paths import database_dir, local_app_data_dir, storage_locator_path
from fluxel.tasks.task_new_dialog import NewTaskDialog
from fluxel.ui.dashboard import DashboardPage
from fluxel.ui.gantt import GanttPage
from fluxel.ui.quick_access_widgets import QuickAccessPanel
from fluxel.ui.tag_manager import TagManagerDialog, TagPickerDialog
from fluxel.ui.task_search import TaskSearchPopup

_log = logging.getLogger(__name__)


class MainWindow(QWidget):
    """ヘッダナビ・カンバン／ショートカット／ファイル・グローバルショートカット。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle(APP_NAME)
        self.resize(480, 720)  # 起動時: 幅 480px × 高さ 720px

        root_layout = QVBoxLayout(self)

        header_frame = QFrame(self)
        header_frame.setFrameShape(QFrame.Shape.NoFrame)
        header_frame.setStyleSheet(
            "QFrame { background-color: #252525; border: none; border-bottom: 1px solid #3d3d3d; }"
        )
        header_outer = QVBoxLayout(header_frame)
        header_outer.setContentsMargins(12, 10, 12, 10)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(0)

        self._nav_kanban = QPushButton("Kanban", header_frame)
        self._nav_dashboard = QPushButton("Dashboard", header_frame)
        self._nav_shortcut = QPushButton("ShortCut", header_frame)
        self._nav_openfile = QPushButton("OpenFile", header_frame)
        self._nav_gantt = QPushButton("Gantt", header_frame)
        self._nav_setting = QPushButton("Setting", header_frame)
        nav_items = (
            (self._nav_kanban, "kanban"),
            (self._nav_dashboard, "dashboard"),
            (self._nav_shortcut, "shortcut"),
            (self._nav_openfile, "openfile"),
            (self._nav_gantt, "gantt"),
            (self._nav_setting, "settings"),
        )
        for button, key in nav_items:
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, nav_key=key: self._set_nav(nav_key))
            nav_row.addWidget(button)
        nav_row.addStretch(1)
        self._search_btn = QPushButton("検索  Ctrl+F", header_frame)
        self._search_btn.setToolTip("タスクをタイトル・本文から検索")
        self._search_btn.clicked.connect(self._activate_task_search)
        nav_row.addWidget(self._search_btn)
        header_outer.addLayout(nav_row)
        root_layout.addWidget(header_frame)

        self._stack = QStackedWidget(self)
        self.kanban = KanbanBoard(self._stack)
        self._stack.addWidget(self.kanban)
        self._dashboard_page = DashboardPage(self._stack)
        self._stack.addWidget(self._dashboard_page)

        self._shortcuts_page = self._build_shortcuts_page()
        self._stack.addWidget(self._shortcuts_page)

        self._openfile_page = self._build_openfile_page()
        self._stack.addWidget(self._openfile_page)
        self._gantt_page = GanttPage(self._stack)
        self._stack.addWidget(self._gantt_page)
        self._settings_page = self._build_settings_page()
        self._stack.addWidget(self._settings_page)

        root_layout.addWidget(self._stack, 1)

        self._search_popup = TaskSearchPopup(
            self,
            importance_color_fn=self.kanban._importance_color,
            is_dark_fn=self.kanban._is_dark_mode,
            open_task=self._open_task_from_search,
        )
        self._copy_toast = QLabel("", self)
        self._copy_toast.setStyleSheet(
            "QLabel { background: rgba(25,25,25,235); color: #ffffff; "
            "border: 2px solid qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6ea8ff, stop:1 #b388ff); "
            "border-radius: 12px; padding: 14px 24px; font-size: 22px; font-weight: 700; }"
        )
        self._copy_toast.hide()
        self._copy_toast_timer = QTimer(self)
        self._copy_toast_timer.setSingleShot(True)
        self._copy_toast_timer.timeout.connect(self._copy_toast.hide)

        self._current_nav = "kanban"
        self._apply_nav_styles()

        action = QAction("Go Kanban", self)
        action.setShortcut("Ctrl+K")
        action.triggered.connect(self.CtrlK_triggered)
        self.addAction(action)

        action_p = QAction("Go ShortCut", self)
        action_p.setShortcut("Ctrl+P")
        action_p.triggered.connect(self.CtrlP_triggered)
        self.addAction(action_p)

        action_o = QAction("Go OpenFile", self)
        action_o.setShortcut("Ctrl+O")
        action_o.triggered.connect(self.CtrlO_triggered)
        self.addAction(action_o)

        action_j = QAction("Action J", self)
        action_j.setShortcut("Ctrl+J")
        action_j.triggered.connect(self.CtrlJ_triggered)
        self.addAction(action_j)

        action_n = QAction("Action N", self)
        action_n.setShortcut("Ctrl+N")
        action_n.triggered.connect(self.CtrlN_triggered)
        self.addAction(action_n)

        action_w = QAction("New Wait Task", self)
        action_w.setShortcut("Ctrl+W")
        action_w.triggered.connect(self.CtrlW_triggered)
        self.addAction(action_w)

        action_x = QAction("Action X", self)
        action_x.setShortcut("Ctrl+X")
        action_x.triggered.connect(self.CtrlX_triggered)
        self.addAction(action_x)

        action_sync = QAction("Sync", self)
        action_sync.setShortcut("Ctrl+S")
        action_sync.triggered.connect(self.CtrlS_triggered)
        self.addAction(action_sync)

        self._setup_navigation_shortcuts()

        self._settings = load_settings()
        self._load_settings_to_ui()

    def _show_settings_menu(self) -> None:
        self._set_nav("settings")

    def _nav_style(self, active: bool) -> str:
        line = "#5c9ccc" if active else "transparent"
        return (
            f"QPushButton {{ color: #e8e8e8; border: none; border-bottom: 2px solid {line}; "
            f"padding: 6px 14px; font-size: 14px; background: transparent; }}"
            f"QPushButton:hover {{ color: #ffffff; }}"
        )

    def _apply_nav_styles(self) -> None:
        k = self._current_nav
        self._nav_kanban.setStyleSheet(self._nav_style(k == "kanban"))
        self._nav_dashboard.setStyleSheet(self._nav_style(k == "dashboard"))
        self._nav_shortcut.setStyleSheet(self._nav_style(k == "shortcut"))
        self._nav_openfile.setStyleSheet(self._nav_style(k == "openfile"))
        self._nav_gantt.setStyleSheet(self._nav_style(k == "gantt"))
        self._nav_setting.setStyleSheet(self._nav_style(k == "settings"))
        self._search_btn.setStyleSheet(
            "QPushButton { color: #e8e8e8; border: 1px solid #4b5563; "
            "border-radius: 6px; padding: 6px 12px; background: #30343b; }"
            "QPushButton:hover { border-color: #5c9ccc; background: #373d46; }"
        )

    def _set_nav(self, key: str) -> None:
        self._current_nav = key
        self._apply_nav_styles()
        if key == "kanban":
            self._stack.setCurrentWidget(self.kanban)
        elif key == "dashboard":
            self._stack.setCurrentWidget(self._dashboard_page)
            self._dashboard_page.refresh()
        elif key == "shortcut":
            self._stack.setCurrentWidget(self._shortcuts_page)
            self._shortcut_panel.focus_search()
        elif key == "openfile":
            self._stack.setCurrentWidget(self._openfile_page)
            self._openfile_panel.focus_search()
        elif key == "gantt":
            self._stack.setCurrentWidget(self._gantt_page)
            self._gantt_page.reload()
        else:
            self._stack.setCurrentWidget(self._settings_page)

    def show_and_focus_nav(self, key: str) -> None:
        """グローバルホットキー呼び出し向け: ウィンドウ前面化 + ページ切替。"""
        self._set_nav(key)
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _build_shortcuts_page(self) -> QWidget:
        w = QWidget(self._stack)
        lay = QVBoxLayout(w)
        self._shortcut_panel = QuickAccessPanel(
            title="よく使うテキストを検索・保存",
            value_label="コマンド",
            add_label="項目を追加",
            execute_label="実行",
            show_editor=True,
            on_search=search_shortcut_items,
            on_add=add_shortcut_item,
            on_update=update_shortcut_item,
            on_delete=delete_shortcut_item,
            tag_candidates_getter=list_known_tags,
            parent=w,
        )
        self._shortcut_panel.execute_item.connect(self._execute_shortcut_item)
        self._shortcut_panel.manage_tags_requested.connect(self._open_tag_manager)
        self._shortcut_panel.edit_tags_requested.connect(self._pick_tags_into)
        row = QHBoxLayout()
        self._shortcut_add_btn = QPushButton("＋ テキストを保存")
        self._shortcut_add_btn.setToolTip("コピーして再利用するテキストやURLを保存します")
        self._shortcut_add_btn.clicked.connect(self._open_shortcut_add_dialog)
        row.addWidget(self._shortcut_add_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        row.addStretch(1)
        lay.addLayout(row)
        self._shortcut_panel.reload()
        lay.addWidget(self._shortcut_panel, 1)
        return w

    def _build_openfile_page(self) -> QWidget:
        w = QWidget(self._stack)
        lay = QVBoxLayout(w)
        self._openfile_panel = QuickAccessPanel(
            title="ファイルやフォルダーを検索・保存",
            value_label="ファイルパス",
            add_label="項目を追加",
            execute_label="開く",
            show_editor=True,
            on_search=search_openfile_items,
            on_add=add_openfile_item,
            on_update=update_openfile_item,
            on_delete=delete_openfile_item,
            tag_candidates_getter=list_known_tags,
            parent=w,
        )
        self._openfile_panel.execute_item.connect(self._execute_openfile_item)
        self._openfile_panel.manage_tags_requested.connect(self._open_tag_manager)
        self._openfile_panel.edit_tags_requested.connect(self._pick_tags_into)
        row = QHBoxLayout()
        self._openfile_add_btn = QPushButton("＋ パスを保存")
        self._openfile_add_btn.setToolTip("ファイルまたはフォルダーを選んで保存します")
        self._openfile_add_btn.clicked.connect(self._open_openfile_add_dialog)
        row.addWidget(self._openfile_add_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        row.addStretch(1)
        lay.addLayout(row)
        self._openfile_panel.reload()
        lay.addWidget(self._openfile_panel, 1)
        return w

    def _build_settings_page(self) -> QWidget:
        page = QWidget(self._stack)
        page.setObjectName("settingsPage")
        page.setStyleSheet(
            "QWidget#settingsPage { background: #15181d; } "
            "QWidget#settingsContent { background: #15181d; } "
            "QFrame[settingsCard='true'] { background: #1d2127; border: 1px solid #303641; border-radius: 8px; } "
            "QLabel[settingsTitle='true'] { color: #f4f7fb; font-size: 15px; font-weight: 600; } "
            "QLabel[settingsHint='true'] { color: #929dac; } "
            "QLabel[settingsPath='true'] { background: #15191e; border: 1px solid #343b46; border-radius: 5px; padding: 8px 10px; color: #dbe2ea; } "
            "QPushButton { min-height: 28px; padding: 0 12px; } "
            "QPushButton[primary='true'] { background: #3978d4; border: 1px solid #4b8ae6; color: white; border-radius: 5px; } "
            "QPushButton[danger='true'] { background: #3a2024; border: 1px solid #8e414b; color: #ffb8bf; border-radius: 5px; } "
        )
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(scroll)
        content.setObjectName("settingsContent")
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 18, 20, 24)
        root.setSpacing(12)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("SETTINGS", content)
        title.setStyleSheet("font-size: 21px; font-weight: 700; color: #f6f8fb;")
        subtitle = QLabel("Manage storage, workflow preferences, backups, and application maintenance.", content)
        subtitle.setProperty("settingsHint", True)
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        self._settings_version = QLabel(content)
        self._settings_check_update_btn = QPushButton("Check for updates", content)
        self._settings_check_update_btn.clicked.connect(self._on_check_update)
        header.addWidget(self._settings_version)
        header.addWidget(self._settings_check_update_btn)
        root.addLayout(header)

        def card(title_text: str, hint_text: str) -> tuple[QFrame, QVBoxLayout]:
            frame = QFrame(content)
            frame.setProperty("settingsCard", True)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(16, 14, 16, 16)
            layout.setSpacing(9)
            label = QLabel(title_text, frame)
            label.setProperty("settingsTitle", True)
            hint = QLabel(hint_text, frame)
            hint.setProperty("settingsHint", True)
            hint.setWordWrap(True)
            layout.addWidget(label)
            layout.addWidget(hint)
            return frame, layout

        storage, storage_layout = card(
            "Storage",
            "Fluxel validates every SQLite database before switching locations. Existing destination databases are never overwritten.",
        )
        database_label = QLabel("DATABASE FOLDER", storage)
        database_label.setProperty("settingsHint", True)
        storage_layout.addWidget(database_label)
        database_row = QHBoxLayout()
        self._settings_database_path = QLabel(storage)
        self._settings_database_path.setProperty("settingsPath", True)
        self._settings_database_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        database_row.addWidget(self._settings_database_path, 1)
        change_database = QPushButton("Change...", storage)
        change_database.clicked.connect(self._move_database_location)
        open_database = QPushButton("Open", storage)
        open_database.clicked.connect(lambda: self._open_storage_folder(database_dir()))
        database_row.addWidget(change_database)
        database_row.addWidget(open_database)
        storage_layout.addLayout(database_row)

        ini_label = QLabel("SETTINGS INI", storage)
        ini_label.setProperty("settingsHint", True)
        storage_layout.addWidget(ini_label)
        ini_row = QHBoxLayout()
        self._settings_ini_path = QLabel(storage)
        self._settings_ini_path.setProperty("settingsPath", True)
        self._settings_ini_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ini_row.addWidget(self._settings_ini_path, 1)
        change_ini = QPushButton("Change...", storage)
        change_ini.clicked.connect(self._move_ini_location)
        open_ini = QPushButton("Open", storage)
        open_ini.clicked.connect(lambda: self._open_storage_folder(settings_ini_path().parent))
        ini_row.addWidget(change_ini)
        ini_row.addWidget(open_ini)
        storage_layout.addLayout(ini_row)
        self._settings_storage_status = QLabel(storage)
        self._settings_storage_status.setWordWrap(True)
        self._settings_storage_status.setProperty("settingsHint", True)
        storage_layout.addWidget(self._settings_storage_status)
        root.addWidget(storage)

        sync_card, sync_layout = card(
            "OneDrive synchronization",
            "Each device keeps its own local SQLite databases. Fluxel exchanges append-only item events through a folder synchronized by the OneDrive desktop client.",
        )
        sync_path_label = QLabel("SYNC FOLDER", sync_card)
        sync_path_label.setProperty("settingsHint", True)
        sync_layout.addWidget(sync_path_label)
        sync_path_row = QHBoxLayout()
        self._settings_sync_path = QLabel(sync_card)
        self._settings_sync_path.setProperty("settingsPath", True)
        self._settings_sync_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sync_path_row.addWidget(self._settings_sync_path, 1)
        choose_sync = QPushButton("Choose...", sync_card)
        choose_sync.clicked.connect(self._choose_sync_folder)
        detect_sync = QPushButton("Set up this device", sync_card)
        detect_sync.clicked.connect(self._detect_sync_folder)
        sync_path_row.addWidget(choose_sync)
        sync_path_row.addWidget(detect_sync)
        sync_layout.addLayout(sync_path_row)

        sync_action_row = QHBoxLayout()
        merge_sync = QPushButton("Import / merge remote data...", sync_card)
        merge_sync.clicked.connect(self._merge_sync_folder)
        sync_now = QPushButton("Sync now   Ctrl+S", sync_card)
        sync_now.setProperty("primary", True)
        sync_now.clicked.connect(lambda: self._run_sync(manual=True))
        open_sync = QPushButton("Open folder", sync_card)
        open_sync.clicked.connect(self._open_sync_folder)
        sync_action_row.addWidget(merge_sync)
        sync_action_row.addStretch(1)
        sync_action_row.addWidget(open_sync)
        sync_action_row.addWidget(sync_now)
        sync_layout.addLayout(sync_action_row)
        self._settings_sync_status = QLabel(sync_card)
        self._settings_sync_status.setWordWrap(True)
        self._settings_sync_status.setProperty("settingsHint", True)
        sync_layout.addWidget(self._settings_sync_status)
        root.addWidget(sync_card)

        kanban, kanban_layout = card("Kanban", "Automatically move inactive Finish tasks to Archive.")
        kanban_row = QHBoxLayout()
        kanban_row.addWidget(QLabel("Archive Finish tasks after", kanban))
        self._settings_archive_days = QSpinBox(kanban)
        self._settings_archive_days.setRange(1, 365)
        self._settings_archive_days.setSuffix(" days")
        self._settings_archive_days.valueChanged.connect(self._on_archive_days_changed)
        kanban_row.addWidget(self._settings_archive_days)
        kanban_row.addStretch(1)
        save_button = QPushButton("Save changes", kanban)
        save_button.setProperty("primary", True)
        save_button.clicked.connect(self._save_settings_from_ui)
        kanban_row.addWidget(save_button)
        kanban_layout.addLayout(kanban_row)
        root.addWidget(kanban)

        backup, backup_layout = card("Backup & export", "Create a point-in-time copy without changing the active storage location.")
        backup_row = QHBoxLayout()
        export_ini = QPushButton("Export settings INI...", backup)
        export_ini.clicked.connect(self._export_ini_now)
        export_sql = QPushButton("Export task database...", backup)
        export_sql.clicked.connect(self._export_sql_now)
        backup_row.addWidget(export_ini)
        backup_row.addWidget(export_sql)
        backup_row.addStretch(1)
        backup_layout.addLayout(backup_row)
        root.addWidget(backup)

        tags, tags_layout = card("Tags", "Create reusable tags or remove tags from all saved shortcuts and paths.")
        self._settings_tag_list = QListWidget(tags)
        self._settings_tag_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._settings_tag_list.setMaximumHeight(140)
        tags_layout.addWidget(self._settings_tag_list)
        tag_row = QHBoxLayout()
        self._settings_tag_input = QLineEdit(tags)
        self._settings_tag_input.setPlaceholderText("Add one or more tags, separated by commas")
        add_tag = QPushButton("Add", tags)
        delete_tag = QPushButton("Delete selected", tags)
        add_tag.clicked.connect(self._add_tags_from_settings)
        self._settings_tag_input.returnPressed.connect(self._add_tags_from_settings)
        delete_tag.clicked.connect(self._delete_selected_setting_tags)
        tag_row.addWidget(self._settings_tag_input, 1)
        tag_row.addWidget(add_tag)
        tag_row.addWidget(delete_tag)
        tags_layout.addLayout(tag_row)
        root.addWidget(tags)

        details, details_layout = card("Application details", "Runtime locations and keyboard reference.")
        self._settings_user_info = QLabel(details)
        self._settings_user_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._settings_user_info.setProperty("settingsHint", True)
        details_layout.addWidget(self._settings_user_info)
        self._settings_shortcuts = QPlainTextEdit(details)
        self._settings_shortcuts.setReadOnly(True)
        self._settings_shortcuts.setMaximumHeight(180)
        details_layout.addWidget(self._settings_shortcuts)
        root.addWidget(details)

        danger, danger_layout = card(
            "Danger zone",
            "Uninstall is available in the installed application. Removing databases permanently deletes tasks, shortcuts, saved paths, and Gantt plans.",
        )
        danger_row = QHBoxLayout()
        keep_data = QPushButton("Uninstall — keep databases", danger)
        keep_data.clicked.connect(lambda: self._uninstall_app(delete_databases=False))
        delete_data = QPushButton("Uninstall — delete databases", danger)
        delete_data.setProperty("danger", True)
        delete_data.clicked.connect(lambda: self._uninstall_app(delete_databases=True))
        available = find_uninstaller() is not None
        keep_data.setEnabled(available)
        delete_data.setEnabled(available)
        danger_row.addWidget(keep_data)
        danger_row.addWidget(delete_data)
        danger_row.addStretch(1)
        danger_layout.addLayout(danger_row)
        if not available:
            note = QLabel("Uninstall controls are disabled in the Python development build.", danger)
            note.setProperty("settingsHint", True)
            danger_layout.addWidget(note)
        root.addWidget(danger)
        root.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return page

    def _shortcuts_text(self) -> str:
        return "\n".join(
            [
                "Ctrl+K: Kanban 画面へ移動",
                "Ctrl+P: ShortCut 画面へ移動",
                "Ctrl+O: OpenFile 画面へ移動",
                "Ctrl+F: 検索ポップアップを表示",
                "Ctrl+N: 画面に応じて新規追加（Kanban/ShortCut/OpenFile/Gantt）",
                "Ctrl+W: Waitステータスで新規タスクを追加（Kanban）",
                "Ctrl+S: OneDrive同期を実行",
                "Ctrl+X: アプリ終了",
                "Ctrl+←/→: ステータス変更",
                "Ctrl+↑/↓: 列内並び替え",
                "↑/↓: 選択移動",
                "←/→: 列移動",
                "Enter: 編集または検索実行",
                "/: 検索欄へフォーカス",
                "Ctrl+Alt+Shift+K/P/O: グローバルホットキー",
            ]
        )

    def _load_settings_to_ui(self) -> None:
        self._settings_user_info.setText(
            f"User: {os.environ.get('USERNAME', '')}\\n"
            f"Database files: Tasks.db, QuickAccess.db, Planning.db\\n"
            f"Storage locator: {storage_locator_path()}"
        )
        self._settings_shortcuts.setPlainText(self._shortcuts_text())
        self._settings_version.setText(f"{APP_NAME} {APP_VERSION}")
        self._settings_archive_days.setValue(self._settings.archive_after_days)
        self.kanban.set_archive_after_days(self._settings.archive_after_days)
        self._refresh_storage_paths_ui()
        self._refresh_sync_ui()
        self._refresh_settings_tags()
        self._setup_tag_line_completer(self._settings_tag_input)

    def _refresh_storage_paths_ui(self) -> None:
        db_directory = database_dir()
        ini_file = settings_ini_path()
        self._settings_database_path.setText(str(db_directory))
        self._settings_database_path.setToolTip(str(db_directory))
        self._settings_ini_path.setText(str(ini_file))
        self._settings_ini_path.setToolTip(str(ini_file))
        if is_onedrive_path(db_directory):
            self._settings_storage_status.setText(
                "OneDrive database location detected. Keep the folder offline and never open Fluxel on two computers at the same time."
            )
            self._settings_storage_status.setStyleSheet("color: #e9b95f;")
        else:
            self._settings_storage_status.setText("Local storage · recommended for SQLite reliability")
            self._settings_storage_status.setStyleSheet("color: #78c99a;")

    def _sync_path(self) -> Path | None:
        raw = (self._settings.sync_folder or "").strip()
        return Path(raw) if raw else None

    def _refresh_sync_ui(self) -> None:
        folder = self._sync_path()
        if folder is None:
            self._settings_sync_path.setText("Not configured")
            self._settings_sync_status.setText(
                "Select Set up this device to detect OneDrive and look for an existing Fluxel sync target."
            )
            self._settings_sync_status.setStyleSheet("color: #929dac;")
            return
        self._settings_sync_path.setText(str(folder))
        self._settings_sync_path.setToolTip(str(folder))
        try:
            summary = inspect_sync_target(folder)
        except SyncTargetError as exc:
            self._settings_sync_status.setText(str(exc))
            self._settings_sync_status.setStyleSheet("color: #ef858f;")
            return
        if summary.initialized:
            self._settings_sync_status.setText(
                f"Ready · {summary.active_item_count} remote items · "
                f"{summary.event_count} events · {summary.device_count} devices"
            )
            self._settings_sync_status.setStyleSheet("color: #78c99a;")
        else:
            self._settings_sync_status.setText(
                "Folder selected. The Fluxel sync structure will be created on the first sync."
            )
            self._settings_sync_status.setStyleSheet("color: #e9b95f;")

    def _store_sync_folder(self, folder: Path) -> None:
        self._settings.sync_folder = str(folder.resolve(strict=False))
        save_settings(self._settings)
        self._refresh_sync_ui()

    def _choose_sync_folder(self) -> None:
        current = self._sync_path()
        candidates = discover_onedrive_candidates()
        default = current or (candidates[0].sync_folder if candidates else Path.home())
        selected = QFileDialog.getExistingDirectory(
            self, "Choose OneDrive sync folder", str(default)
        )
        if not selected:
            return
        folder = Path(selected)
        if not is_onedrive_path(folder):
            QMessageBox.warning(
                self,
                "OneDrive required",
                "This version supports folders inside OneDrive only. Choose a folder under your OneDrive directory.",
            )
            return
        self._store_sync_folder(folder)
        summary = inspect_sync_target(folder)
        if summary.initialized and summary.event_count:
            self._offer_remote_merge(summary)

    def _detect_sync_folder(self) -> None:
        candidates = discover_onedrive_candidates()
        if not candidates:
            QMessageBox.information(
                self,
                "OneDrive not found",
                "Fluxel could not detect a local OneDrive folder. Start the OneDrive desktop client, or use Choose to select it manually.",
            )
            return
        candidate = candidates[0]
        detail = (
            f"OneDrive was detected at:\n{candidate.onedrive_root}\n\n"
            f"Suggested Fluxel sync folder:\n{candidate.sync_folder}"
        )
        if candidate.initialized:
            detail += f"\n\nExisting sync data: {candidate.event_count} events"
        answer = QMessageBox.question(
            self,
            "Set up this device",
            detail + "\n\nUse this folder for synchronization?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        candidate.sync_folder.mkdir(parents=True, exist_ok=True)
        self._store_sync_folder(candidate.sync_folder)
        if candidate.initialized and candidate.event_count:
            self._offer_remote_merge(inspect_sync_target(candidate.sync_folder))

    def _offer_remote_merge(self, summary) -> None:
        answer = QMessageBox.question(
            self,
            "Remote data found",
            f"Fluxel found an existing sync target.\n\n"
            f"Folder: {summary.folder}\n"
            f"Active remote items: {summary.active_item_count}\n"
            f"Event history: {summary.event_count}\n"
            f"Known devices: {summary.device_count}\n\n"
            "Import and merge this data into the local databases now? Local-only items are preserved and uploaded.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run_sync(manual=True, initial_setup=True)

    def _merge_sync_folder(self) -> None:
        folder = self._sync_path()
        if folder is None:
            self._detect_sync_folder()
            return
        try:
            summary = inspect_sync_target(folder)
        except SyncTargetError as exc:
            QMessageBox.critical(self, "Synchronization", str(exc))
            return
        if not summary.initialized or summary.event_count == 0:
            QMessageBox.information(
                self, "Synchronization", "No remote Fluxel data was found in this folder."
            )
            return
        self._offer_remote_merge(summary)

    def _open_sync_folder(self) -> None:
        folder = self._sync_path()
        if folder is None:
            QMessageBox.information(self, "Synchronization", "Configure a sync folder first.")
            return
        folder.mkdir(parents=True, exist_ok=True)
        self._open_storage_folder(folder)

    def _run_sync(self, *, manual: bool, initial_setup: bool = False) -> None:
        folder = self._sync_path()
        if folder is None:
            if manual:
                self._set_nav("settings")
                QMessageBox.information(
                    self,
                    "Synchronization",
                    "Configure a OneDrive sync folder in Settings first.",
                )
            return
        if not folder.exists():
            if manual:
                QMessageBox.warning(
                    self,
                    "Synchronization",
                    f"The sync folder is not available. Check that OneDrive is running.\n{folder}",
                )
            return
        self._settings_sync_status.setText("Synchronizing...")
        self._settings_sync_status.setStyleSheet("color: #77aef4;")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            report = sync_folder(folder)
        except (SyncBusyError, SyncTargetError, OSError, ValueError) as exc:
            self._settings_sync_status.setText(f"Sync failed · {exc}")
            self._settings_sync_status.setStyleSheet("color: #ef858f;")
            if manual:
                QMessageBox.critical(self, "Synchronization failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_after_sync()
        self._refresh_sync_ui()
        if manual:
            title = "Initial merge complete" if initial_setup else "Synchronization complete"
            QMessageBox.information(
                self,
                title,
                f"Downloaded: {report.downloaded}\n"
                f"Uploaded: {report.uploaded}\n"
                f"Deleted: {report.deleted}\n"
                f"Conflicts preserved: {report.conflicts}",
            )
        elif report.changed:
            self._show_toast("Synced")

    def _refresh_after_sync(self) -> None:
        self.kanban.refresh_task_cards(reload_db=True)
        self._shortcut_panel.reload()
        self._openfile_panel.reload()
        self._gantt_page.reload()
        self._dashboard_page.refresh()
        self._refresh_settings_tags()

    def CtrlS_triggered(self) -> None:
        self._run_sync(manual=True)

    def _save_settings_from_ui(self) -> None:
        self._settings = AppSettings(
            archive_after_days=self._settings_archive_days.value(),
            export_ini_path=self._settings.export_ini_path,
            export_sql_path=self._settings.export_sql_path,
            sync_folder=self._settings.sync_folder,
        )
        save_settings(self._settings)
        self.kanban.set_archive_after_days(self._settings.archive_after_days)
        self.kanban.refresh_task_cards(reload_db=True)
        QMessageBox.information(self, "Settings", "Settings saved.")

    def _open_storage_folder(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "Storage", f"Could not open the folder.\\n{path}")

    def _confirm_onedrive_location(self, path: Path) -> bool:
        if not is_onedrive_path(path):
            return True
        answer = QMessageBox.warning(
            self,
            "OneDrive storage warning",
            "SQLite is not a sync database. Use this location only when:\n\n"
            "• the folder is set to Always keep on this device\n"
            "• Fluxel is never open on two computers at once\n"
            "• OneDrive finishes syncing before another computer opens Fluxel\n\n"
            "Continue with this OneDrive location?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _move_database_location(self) -> None:
        source = database_dir()
        selected = QFileDialog.getExistingDirectory(self, "Choose database folder", str(source))
        if not selected:
            return
        target = Path(selected)
        if not self._confirm_onedrive_location(target):
            return
        answer = QMessageBox.question(
            self,
            "Move databases",
            f"Move all Fluxel databases?\\n\\nFrom: {source}\\nTo: {target}\\n\\n"
            "Tasks.db, QuickAccess.db, and Planning.db will be validated before the active location changes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            move_database_directory(target)
            ensure_tasks_table()
            ensure_quick_access_tables()
            ensure_gantt_tables()
            self.kanban.refresh_task_cards(reload_db=True)
            self._shortcut_panel.reload()
            self._openfile_panel.reload()
            self._gantt_page.reload()
            self._dashboard_page.refresh()
            self._refresh_settings_tags()
            self._refresh_storage_paths_ui()
        except StorageMoveError as exc:
            QMessageBox.critical(self, "Storage move failed", str(exc))
            return
        QMessageBox.information(self, "Storage moved", f"Database location changed to:\n{target}")

    def _move_ini_location(self) -> None:
        source = settings_ini_path()
        selected = QFileDialog.getExistingDirectory(self, "Choose settings folder", str(source.parent))
        if not selected:
            return
        target = Path(selected) / "settings.ini"
        if not self._confirm_onedrive_location(target.parent):
            return
        answer = QMessageBox.question(
            self,
            "Move settings",
            f"Move the settings file?\\n\\nFrom: {source}\\nTo: {target}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            move_settings_file(target)
            self._settings = load_settings()
            self._refresh_storage_paths_ui()
        except StorageMoveError as exc:
            QMessageBox.critical(self, "Settings move failed", str(exc))
            return
        QMessageBox.information(self, "Settings moved", f"Settings location changed to:\n{target}")

    def _uninstall_app(self, *, delete_databases: bool) -> None:
        uninstaller = find_uninstaller()
        if uninstaller is None:
            QMessageBox.information(self, "Uninstall Fluxel", "Uninstall is only available in the installed application.")
            return
        if delete_databases:
            listed = "\\n".join(str(path) for path in database_paths())
            message = (
                "Fluxel will be uninstalled and all database files will be permanently deleted.\\n\\n"
                f"Files scheduled for deletion:\n{listed}\\n\\nThis cannot be undone."
            )
            phrase = "DELETE DATA"
        else:
            message = (
                "Fluxel will be uninstalled. Your database files will remain and can be used by a later installation."
            )
            phrase = "UNINSTALL"
        answer = QMessageBox.warning(
            self,
            "Confirm uninstall",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        entered, ok = QInputDialog.getText(self, "Final confirmation", f"Type {phrase} to continue:")
        if not ok or entered.strip() != phrase:
            QMessageBox.information(self, "Uninstall cancelled", "The confirmation text did not match.")
            return
        arguments = ["/FLUXELDELETEDB=1"] if delete_databases else []
        result = QProcess.startDetached(str(uninstaller), arguments)
        started = result[0] if isinstance(result, tuple) else bool(result)
        if not started:
            QMessageBox.critical(self, "Uninstall Fluxel", "Could not start the uninstaller.")
            return
        QApplication.instance().quit()

    def _on_archive_days_changed(self, value: int) -> None:
        self.kanban.set_archive_after_days(value)

    def _on_check_update(self) -> None:
        QMessageBox.information(
            self,
            "更新確認",
            "将来ここでWeb APIを呼び出し、最新バージョン判定を行います。",
        )

    def _export_ini_now(self) -> None:
        src = settings_ini_path()
        if not src.is_file():
            save_settings(self._settings)
        default_path = self._settings.export_ini_path or str(settings_ini_path().parent / "Fluxel_settings.ini")
        path, _ = QFileDialog.getSaveFileName(self, "INIをエクスポート", default_path, "INI (*.ini);;All Files (*.*)")
        if not path:
            return
        shutil.copy2(str(settings_ini_path()), path)
        self._settings.export_ini_path = path
        save_settings(self._settings)
        QMessageBox.information(self, "Export", f"INI を保存しました。\n{path}")

    def _export_sql_now(self) -> None:
        default_path = self._settings.export_sql_path or str(local_app_data_dir() / "Fluxel_Tasks.db")
        path, _ = QFileDialog.getSaveFileName(self, "SQLをエクスポート", default_path, "DB (*.db *.sqlite *.sql);;All Files (*.*)")
        if not path:
            return
        shutil.copy2(TASK_DB, path)
        self._settings.export_sql_path = path
        save_settings(self._settings)
        QMessageBox.information(self, "Export", f"SQL(DB) を保存しました。\n{path}")

    def _execute_shortcut_item(self, item_id: str, title: str, command: str, _tags: str) -> None:
        phrase = (command or "").strip()
        if not phrase:
            return
        QApplication.clipboard().setText(phrase)
        self._show_toast("Copied")
        bump_shortcut_use_count(item_id)
        self._shortcut_panel.reload()

    def _execute_openfile_item(self, item_id: str, _title: str, file_path: str, _tags: str) -> None:
        path = (file_path or "").strip()
        if not path:
            return
        target = Path(path)
        if not target.exists():
            QMessageBox.warning(self, "OpenFile", f"ファイルが見つかりません。\n{path}")
            return
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        if not ok:
            QMessageBox.warning(self, "OpenFile", f"ファイルを開けませんでした。\n{path}")
            return
        bump_openfile_use_count(item_id)
        self._openfile_panel.reload()

    def _show_toast(self, message: str, timeout_ms: int = 1200) -> None:
        self._copy_toast.setText(message)
        self._copy_toast.adjustSize()
        x = (self.width() - self._copy_toast.width()) // 2
        y = (self.height() - self._copy_toast.height()) // 2
        self._copy_toast.move(max(0, x), max(0, y))
        self._copy_toast.raise_()
        self._copy_toast.show()
        self._copy_toast_timer.start(max(int(timeout_ms), 300))

    def _setup_tag_line_completer(self, line_edit: QLineEdit) -> None:
        model = QStringListModel([], line_edit)
        comp = QCompleter(model, line_edit)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        line_edit.setCompleter(comp)

        def _prefix(text: str) -> str:
            i = text.rfind(",")
            return text[i + 1 :].strip().lower()

        def _refresh() -> None:
            pfx = _prefix(line_edit.text())
            if not pfx:
                comp.popup().hide()
                model.setStringList([])
                return
            tags = list_known_tags()
            tags = [t for t in tags if pfx in t.lower()]
            model.setStringList(tags[:80])
            if tags:
                comp.complete()

        def _apply(selected: str) -> None:
            text = line_edit.text()
            i = text.rfind(",")
            base = text[: i + 1] if i >= 0 else ""
            if base and not base.endswith((" ", ",")):
                base += " "
            line_edit.setText(f"{base}{selected}, ")

        line_edit.textEdited.connect(_refresh)
        comp.activated[str].connect(_apply)
        line_edit.returnPressed.connect(_refresh)

    def _refresh_settings_tags(self) -> None:
        self._settings_tag_list.clear()
        for t in list_known_tags():
            self._settings_tag_list.addItem(t)

    def _open_tag_manager(self) -> None:
        dialog = TagManagerDialog(parent=self)
        dialog.exec()
        self._refresh_settings_tags()
        self._shortcut_panel.reload()
        self._openfile_panel.reload()

    def _pick_tags_into(self, line_edit: QLineEdit) -> None:
        dialog = TagPickerDialog(line_edit.text(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        line_edit.setText(dialog.selected_tags())
        self._refresh_settings_tags()

    def _add_tags_from_settings(self) -> None:
        raw = self._settings_tag_input.text().strip()
        if not raw:
            return
        add_known_tag(raw)
        self._settings_tag_input.clear()
        self._refresh_settings_tags()

    def _delete_selected_setting_tags(self) -> None:
        items = self._settings_tag_list.selectedItems()
        if not items:
            QMessageBox.information(self, "タグ", "削除するタグを選択してください。")
            return
        answer = QMessageBox.question(
            self,
            "タグを削除",
            f"{len(items)}件のタグを削除しますか？\n保存項目からもタグが外れます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for item in items:
            delete_known_tag(item.text())
        self._refresh_settings_tags()
        self._shortcut_panel.reload()
        self._openfile_panel.reload()

    def _open_shortcut_add_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("ShortCut 新規追加")
        dialog.setModal(True)
        lay = QVBoxLayout(dialog)
        title_edit = QLineEdit(dialog)
        title_edit.setPlaceholderText("タイトル")
        cmd_edit = QLineEdit(dialog)
        cmd_edit.setPlaceholderText("コマンド / URL / nav:kanban など")
        tags_edit = QLineEdit(dialog)
        tags_edit.setPlaceholderText("タグ（任意）")
        self._setup_tag_line_completer(tags_edit)
        lay.addWidget(QLabel("タイトル", dialog))
        lay.addWidget(title_edit)
        lay.addWidget(QLabel("コマンド", dialog))
        lay.addWidget(cmd_edit)
        tag_label_row = QHBoxLayout()
        tag_label_row.addWidget(QLabel("タグ", dialog))
        tag_label_row.addStretch(1)
        btn_pick_tags = QPushButton("候補から選択・追加…", dialog)
        btn_pick_tags.clicked.connect(lambda: self._pick_tags_into(tags_edit))
        tag_label_row.addWidget(btn_pick_tags)
        lay.addLayout(tag_label_row)
        lay.addWidget(tags_edit)
        row = QHBoxLayout()
        btn_cancel = QPushButton("キャンセル", dialog)
        btn_ok = QPushButton("追加", dialog)
        btn_cancel.clicked.connect(dialog.reject)
        btn_ok.clicked.connect(dialog.accept)
        sc_ctrl_enter = QShortcut(QKeySequence("Ctrl+Return"), dialog)
        sc_ctrl_enter_num = QShortcut(QKeySequence("Ctrl+Enter"), dialog)
        sc_ctrl_enter.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_ctrl_enter_num.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_ctrl_enter.activated.connect(dialog.accept)
        sc_ctrl_enter_num.activated.connect(dialog.accept)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        lay.addLayout(row)
        title_edit.setFocus()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        title = title_edit.text().strip()
        command = cmd_edit.text().strip()
        tags = tags_edit.text().strip()
        if not title or not command:
            QMessageBox.warning(self, "ShortCut", "タイトルとコマンドは必須です。")
            return
        add_shortcut_item(title, command, tags)
        self._shortcut_panel.reload()

    def _open_openfile_add_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("ファイル / フォルダーを保存")
        dialog.setModal(True)
        dialog.setMinimumWidth(520)
        lay = QVBoxLayout(dialog)
        intro = QLabel(
            "一度保存すれば、名前・パス・タグで検索して Enter ですぐ開けます。",
            dialog,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("QLabel { color: #9ca3af; padding-bottom: 6px; }")
        lay.addWidget(intro)
        title_edit = QLineEdit(dialog)
        title_edit.setPlaceholderText("タイトル")
        path_edit = QLineEdit(dialog)
        path_edit.setPlaceholderText("ファイルまたはフォルダーのパス")
        path_edit.setClearButtonEnabled(True)
        tags_edit = QLineEdit(dialog)
        tags_edit.setPlaceholderText("タグ（任意）")
        self._setup_tag_line_completer(tags_edit)
        lay.addWidget(QLabel("タイトル", dialog))
        lay.addWidget(title_edit)
        lay.addWidget(QLabel("ファイルパス", dialog))
        lay.addWidget(path_edit)
        browse_row = QHBoxLayout()
        btn_browse = QPushButton("ファイルを選ぶ", dialog)
        btn_browse_dir = QPushButton("フォルダーを選ぶ", dialog)
        browse_row.addWidget(btn_browse)
        browse_row.addWidget(btn_browse_dir)
        browse_row.addStretch(1)
        lay.addLayout(browse_row)
        tag_label_row = QHBoxLayout()
        tag_label_row.addWidget(QLabel("タグ", dialog))
        tag_label_row.addStretch(1)
        btn_pick_tags = QPushButton("候補から選択・追加…", dialog)
        btn_pick_tags.clicked.connect(lambda: self._pick_tags_into(tags_edit))
        tag_label_row.addWidget(btn_pick_tags)
        lay.addLayout(tag_label_row)
        lay.addWidget(tags_edit)
        row = QHBoxLayout()
        btn_cancel = QPushButton("キャンセル", dialog)
        btn_ok = QPushButton("追加", dialog)
        btn_cancel.clicked.connect(dialog.reject)
        btn_ok.clicked.connect(dialog.accept)
        sc_ctrl_enter = QShortcut(QKeySequence("Ctrl+Return"), dialog)
        sc_ctrl_enter_num = QShortcut(QKeySequence("Ctrl+Enter"), dialog)
        sc_ctrl_enter.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_ctrl_enter_num.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_ctrl_enter.activated.connect(dialog.accept)
        sc_ctrl_enter_num.activated.connect(dialog.accept)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        lay.addLayout(row)

        def _browse_file() -> None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "ファイルを開く",
                "",
                "すべてのファイル (*.*)",
            )
            if not path:
                return
            path_edit.setText(path)
            if not title_edit.text().strip():
                title_edit.setText(os.path.basename(path))

        def _browse_directory() -> None:
            path = QFileDialog.getExistingDirectory(self, "フォルダーを選ぶ", "")
            if not path:
                return
            path_edit.setText(path)
            if not title_edit.text().strip():
                title_edit.setText(os.path.basename(path.rstrip("\\/")) or path)

        def _fill_title_from_path(path: str) -> None:
            if title_edit.text().strip() or not path.strip():
                return
            title_edit.setText(os.path.basename(path.rstrip("\\/")))

        btn_browse.clicked.connect(_browse_file)
        btn_browse_dir.clicked.connect(_browse_directory)
        path_edit.textChanged.connect(_fill_title_from_path)
        path_edit.setFocus()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        title = title_edit.text().strip()
        file_path = path_edit.text().strip()
        tags = tags_edit.text().strip()
        if not title or not file_path:
            QMessageBox.warning(self, "OpenFile", "表示名とパスは必須です。")
            return
        normalized_path = os.path.expandvars(os.path.expanduser(file_path))
        if not Path(normalized_path).exists():
            QMessageBox.warning(
                self,
                "OpenFile",
                f"指定したファイルまたはフォルダーが見つかりません。\n{file_path}",
            )
            return
        item_id = add_openfile_item(title, normalized_path, tags)
        self._openfile_panel.reload()
        self._openfile_panel.select_item(item_id)
        self._show_toast("パスを保存しました")

    def _setup_navigation_shortcuts(self) -> None:
        """メインウィンドウにフォーカスがあってもカード移動が効くよう QShortcut を親に付ける。"""
        k = self.kanban
        self._shortcut_up = QShortcut(QKeySequence(Qt.Key.Key_Up), self)
        self._shortcut_down = QShortcut(QKeySequence(Qt.Key.Key_Down), self)
        self._shortcut_left = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        self._shortcut_right = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        self._shortcut_ctrl_left = QShortcut(
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Left), self
        )
        self._shortcut_ctrl_right = QShortcut(
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Right), self
        )
        self._shortcut_ctrl_up = QShortcut(
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Up), self
        )
        self._shortcut_ctrl_down = QShortcut(
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Down), self
        )
        self._shortcut_alt_up = QShortcut(QKeySequence("Alt+Up"), self)
        self._shortcut_alt_down = QShortcut(QKeySequence("Alt+Down"), self)
        self._shortcut_ctrl_alt_up = QShortcut(
            QKeySequence("Ctrl+Alt+Up"), self
        )
        self._shortcut_ctrl_alt_down = QShortcut(
            QKeySequence("Ctrl+Alt+Down"), self
        )
        self._shortcut_enter = QShortcut(QKeySequence(Qt.Key.Key_Return), self)
        self._shortcut_enter_num = QShortcut(QKeySequence(Qt.Key.Key_Enter), self)
        self._shortcut_find = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)

        for shortcut in (
            self._shortcut_up,
            self._shortcut_down,
            self._shortcut_left,
            self._shortcut_right,
            self._shortcut_ctrl_left,
            self._shortcut_ctrl_right,
            self._shortcut_ctrl_up,
            self._shortcut_ctrl_down,
            self._shortcut_alt_up,
            self._shortcut_alt_down,
            self._shortcut_ctrl_alt_up,
            self._shortcut_ctrl_alt_down,
            self._shortcut_enter,
            self._shortcut_enter_num,
            self._shortcut_find,
        ):
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self._shortcut_up.activated.connect(self._on_shortcut_up)
        self._shortcut_down.activated.connect(self._on_shortcut_down)
        self._shortcut_left.activated.connect(self._on_shortcut_left)
        self._shortcut_right.activated.connect(self._on_shortcut_right)
        self._shortcut_ctrl_left.activated.connect(lambda: k._move_selected_task_status(-1))
        self._shortcut_ctrl_right.activated.connect(lambda: k._move_selected_task_status(1))
        self._shortcut_ctrl_up.activated.connect(
            lambda: self._on_ctrl_vertical(-1)
        )
        self._shortcut_ctrl_down.activated.connect(
            lambda: self._on_ctrl_vertical(1)
        )
        self._shortcut_alt_up.activated.connect(
            lambda: self._navigate_gantt_project(-1)
        )
        self._shortcut_alt_down.activated.connect(
            lambda: self._navigate_gantt_project(1)
        )
        self._shortcut_ctrl_alt_up.activated.connect(
            lambda: self._move_gantt_term_project(-1)
        )
        self._shortcut_ctrl_alt_down.activated.connect(
            lambda: self._move_gantt_term_project(1)
        )
        self._shortcut_enter.activated.connect(self._on_shortcut_enter)
        self._shortcut_enter_num.activated.connect(self._on_shortcut_enter)
        self._shortcut_find.activated.connect(self._activate_task_search)

    def _activate_task_search(self) -> None:
        self._search_popup.show_near_anchor(self._search_btn, focus_line=True)

    def _open_task_from_search(self, task_id: str) -> None:
        self._search_popup.hide()
        self.kanban._open_task_edit_dialog(task_id)

    def keyPressEvent(self, event) -> None:
        k = self.kanban
        if (
            event.key() == Qt.Key.Key_Slash
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self._current_nav in {"shortcut", "openfile"}
        ):
            if self._current_nav == "shortcut":
                self._shortcut_panel.focus_search()
            else:
                self._openfile_panel.focus_search()
            event.accept()
            return
        if (
            event.key() == Qt.Key.Key_Slash
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self._search_popup.isVisible()
        ):
            self._search_popup.focus_search_line()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Up:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                k.reorder_selected_card(-1)
            else:
                if self._search_popup.isVisible() and self._search_popup.move_selection(-1):
                    event.accept()
                    return
                k._move_selection_vertical(-1)
            return
        if event.key() == Qt.Key.Key_Down:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                k.reorder_selected_card(1)
            else:
                if self._search_popup.isVisible() and self._search_popup.move_selection(1):
                    event.accept()
                    return
                k._move_selection_vertical(1)
            return
        if event.key() == Qt.Key.Key_Left:
            if self._search_popup.isVisible() and self._search_popup.move_pane(-1):
                event.accept()
                return
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                k._move_selected_task_status(-1)
            else:
                k._move_selection_horizontal(-1)
            return
        if event.key() == Qt.Key.Key_Right:
            if self._search_popup.isVisible() and self._search_popup.move_pane(1):
                event.accept()
                return
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                k._move_selected_task_status(1)
            else:
                k._move_selection_horizontal(1)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            k._trigger_selected_card()
            return
        super().keyPressEvent(event)

    def _on_shortcut_up(self) -> None:
        if self._current_nav in {"dashboard", "settings"}:
            return
        if self._current_nav == "gantt":
            self._gantt_page.move_selection(-1)
            return
        # QuickAccess ではフォーカス位置に関係なく矢印キーを一覧選択へ渡す。
        # 検索文字列の入力フォーカスは維持するため、続けて文字入力もできる。
        if self._current_nav == "shortcut":
            self._shortcut_panel.move_selection(-1)
            return
        if self._current_nav == "openfile":
            self._openfile_panel.move_selection(-1)
            return
        if self._search_popup.isVisible() and self._search_popup.move_selection(-1):
            return
        self.kanban._move_selection_vertical(-1)

    def _on_shortcut_down(self) -> None:
        if self._current_nav in {"dashboard", "settings"}:
            return
        if self._current_nav == "gantt":
            self._gantt_page.move_selection(1)
            return
        if self._current_nav == "shortcut":
            self._shortcut_panel.move_selection(1)
            return
        if self._current_nav == "openfile":
            self._openfile_panel.move_selection(1)
            return
        if self._search_popup.isVisible() and self._search_popup.move_selection(1):
            return
        self.kanban._move_selection_vertical(1)

    def _on_ctrl_vertical(self, direction: int) -> None:
        if self._current_nav == "gantt":
            self._gantt_page.reorder_selected_term(direction)
            return
        self.kanban.reorder_selected_card(direction)

    def _navigate_gantt_project(self, direction: int) -> None:
        if self._current_nav == "gantt":
            self._gantt_page.navigate_project(direction)

    def _move_gantt_term_project(self, direction: int) -> None:
        if self._current_nav == "gantt":
            self._gantt_page.move_selected_to_project(direction)

    def _on_shortcut_left(self) -> None:
        if self._current_nav in {"dashboard", "gantt", "settings"}:
            return
        if self._search_popup.isVisible() and self._search_popup.move_pane(-1):
            return
        self.kanban._move_selection_horizontal(-1)

    def _on_shortcut_right(self) -> None:
        if self._current_nav in {"dashboard", "gantt", "settings"}:
            return
        if self._search_popup.isVisible() and self._search_popup.move_pane(1):
            return
        self.kanban._move_selection_horizontal(1)

    def _on_shortcut_enter(self) -> None:
        if self._current_nav in {"dashboard", "gantt", "settings"}:
            return
        fw = QApplication.focusWidget()
        fw_name = type(fw).__name__ if fw is not None else ""
        in_popup = False
        p = fw
        while p is not None:
            if p is self._search_popup:
                in_popup = True
                break
            p = p.parentWidget()
        if self._search_popup.isVisible():
            if isinstance(fw, QLineEdit) and self._search_popup.has_pending_query():
                self._search_popup.execute_search_now()
                return
            if self._search_popup.has_selected_card() and self._search_popup.activate_selected():
                return
            if isinstance(fw, QLineEdit):
                self._search_popup.execute_search_now()
                return
            if self._search_popup.activate_selected():
                return
        # ページ状態ごとに Enter の意味を分岐する
        if self._current_nav == "shortcut":
            if isinstance(fw, QLineEdit) and self._shortcut_panel.isAncestorOf(fw):
                self._shortcut_panel.handle_enter()
                return
            self._shortcut_panel.execute_selected()
            return
        if self._current_nav == "openfile":
            if isinstance(fw, QLineEdit) and self._openfile_panel.isAncestorOf(fw):
                self._openfile_panel.handle_enter()
                return
            self._openfile_panel.execute_selected()
            return
        self.kanban._trigger_selected_card()

    def CtrlK_triggered(self) -> None:
        self._set_nav("kanban")

    def CtrlP_triggered(self) -> None:
        self._set_nav("shortcut")

    def CtrlO_triggered(self) -> None:
        self._set_nav("openfile")

    def CtrlJ_triggered(self) -> None:
        text, ok = QInputDialog.getText(self, "入力", "コマンドを入力:")
        if ok:
            _log.debug("Ctrl+J input: %s", text)

    def CtrlN_triggered(self) -> None:
        if self._current_nav == "shortcut":
            self._open_shortcut_add_dialog()
            return
        if self._current_nav == "openfile":
            self._open_openfile_add_dialog()
            return
        if self._current_nav == "gantt":
            self._gantt_page.add_term()
            return
        if self._current_nav != "kanban":
            return
        self._open_new_kanban_task("todo")

    def CtrlW_triggered(self) -> None:
        if self._current_nav != "kanban":
            return
        self._open_new_kanban_task("wait")

    def _open_new_kanban_task(self, initial_status: str) -> None:
        dialog = NewTaskDialog(self, initial_status=initial_status)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            _log.debug("new task cancelled status=%s", initial_status)
            return
        new_id = dialog.save_new_task()
        ts = datetime.now().isoformat(timespec="seconds")
        task_name, date = dialog.get_values()
        _log.debug(
            "new task saved id=%s name=%r end_date=%s importance=%r status=%s at %s",
            new_id,
            task_name,
            date.toString("yyyy-MM-dd"),
            dialog.importance_input.currentText(),
            dialog.get_status_key(),
            ts,
        )
        self.kanban.set_selected_task_id(new_id)
        self.kanban.refresh_task_cards(reload_db=True)
        QTimer.singleShot(250, lambda: self._run_sync(manual=False))

    def CtrlX_triggered(self) -> None:
        _log.debug("Ctrl+X quit")
        QApplication.instance().quit()
