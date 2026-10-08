"""Windows 用グローバルホットキー登録。"""

from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter

_log = logging.getLogger(__name__)

# Win32 constants
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_K = 0x4B
VK_P = 0x50
VK_O = 0x4F


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint32),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint32),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
        ("lPrivate", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class HotkeyBinding:
    """1 つのグローバルホットキー定義。"""

    hotkey_id: int
    virtual_key: int
    callback: Callable[[], None]
    label: str


class GlobalHotkeyManager(QAbstractNativeEventFilter):
    """RegisterHotKey でグローバルホットキーを受ける。"""

    def __init__(self, bindings: list[HotkeyBinding]) -> None:
        super().__init__()
        self._bindings = {b.hotkey_id: b for b in bindings}
        self._registered_ids: set[int] = set()

    def register(self) -> None:
        user32 = ctypes.windll.user32
        modifiers = MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT
        for binding in self._bindings.values():
            ok = bool(user32.RegisterHotKey(None, binding.hotkey_id, modifiers, binding.virtual_key))
            if ok:
                self._registered_ids.add(binding.hotkey_id)
                _log.info("global hotkey registered: %s", binding.label)
            else:
                err = ctypes.get_last_error()
                _log.warning("global hotkey register failed: %s (winerr=%s)", binding.label, err)

    def unregister_all(self) -> None:
        user32 = ctypes.windll.user32
        for hotkey_id in sorted(self._registered_ids):
            user32.UnregisterHotKey(None, hotkey_id)
        self._registered_ids.clear()

    def nativeEventFilter(self, event_type, message):
        if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        msg = _MSG.from_address(int(message))
        if msg.message != WM_HOTKEY:
            return False, 0
        binding = self._bindings.get(int(msg.wParam))
        if binding is None:
            return False, 0
        binding.callback()
        return True, 0
