"""アプリケーションエントリ（Qt プラグイン設定・ログ・ウィンドウ起動）。"""

import logging
import os
import platform
import sys

import PySide6
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from fluxel.core.demo_seed import seed_demo_tasks_if_requested
from fluxel.core.db_migrations import migrate_databases
from fluxel.paths import app_icon_path
from fluxel.ui.global_hotkeys import (
    GlobalHotkeyManager,
    HotkeyBinding,
    VK_K,
    VK_O,
    VK_P,
)
from fluxel.ui.main_window import MainWindow


def _cli_seed_flags() -> bool:
    """--seed-demo / --seed-demo-force を argv から外し、force なら True。"""
    force = "--seed-demo-force" in sys.argv
    if "--seed-demo" in sys.argv or force:
        os.environ["FLUXEL_SEED_DEMO"] = "1"
    sys.argv = [
        arg for arg in sys.argv if arg not in ("--seed-demo", "--seed-demo-force")
    ]
    return force


if __name__ == "__main__":
    dirname = os.path.dirname(PySide6.__file__)
    plugin_path = os.path.join(dirname, "plugins", "platforms")
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugin_path

    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("FLUXEL_DEBUG") else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    _seed_force = _cli_seed_flags()
    migrate_databases()
    seed_demo_tasks_if_requested(force=_seed_force)

    app = QApplication(sys.argv)
    ico_path = app_icon_path()
    app_icon = QIcon(str(ico_path)) if ico_path is not None else QIcon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()
    hotkeys = None
    if platform.system() == "Windows":
        hotkeys = GlobalHotkeyManager(
            [
                HotkeyBinding(
                    hotkey_id=1,
                    virtual_key=VK_K,
                    callback=lambda: window.show_and_focus_nav("kanban"),
                    label="Ctrl+Alt+Shift+K (Kanban)",
                ),
                HotkeyBinding(
                    hotkey_id=2,
                    virtual_key=VK_P,
                    callback=lambda: window.show_and_focus_nav("shortcut"),
                    label="Ctrl+Alt+Shift+P (ShortCut)",
                ),
                HotkeyBinding(
                    hotkey_id=3,
                    virtual_key=VK_O,
                    callback=lambda: window.show_and_focus_nav("openfile"),
                    label="Ctrl+Alt+Shift+O (OpenFile)",
                ),
            ]
        )
        hotkeys.register()
        app.installNativeEventFilter(hotkeys)

    exit_code = app.exec()
    if hotkeys is not None:
        hotkeys.unregister_all()
    sys.exit(exit_code)
