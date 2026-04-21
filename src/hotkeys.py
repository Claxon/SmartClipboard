from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_V = 0x56
VK_C = 0x43
VK_OEM_2 = 0xBF  # '/?' on US layout


@dataclass
class HotkeySpec:
    id: int
    mods: int
    vk: int
    name: str


DEFAULT_HOTKEYS: list[HotkeySpec] = [
    HotkeySpec(1, MOD_CONTROL, VK_OEM_2, "cycle_popup"),            # Ctrl+/
    HotkeySpec(2, MOD_CONTROL | MOD_ALT, VK_V, "paste_secondary"),  # Ctrl+Alt+V
    HotkeySpec(3, MOD_CONTROL | MOD_SHIFT, VK_V, "open_history"),   # Ctrl+Shift+V
    HotkeySpec(4, MOD_CONTROL | MOD_ALT, VK_C, "push_secondary"),   # Ctrl+Alt+C
]


class HotkeyThread(QThread):
    hotkey_fired = Signal(str)

    def __init__(self, specs: list[HotkeySpec]):
        super().__init__()
        self._specs = specs
        self._thread_id = 0
        self._id_to_name = {s.id: s.name for s in specs}
        self._ready = False

    def run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        registered: list[int] = []
        for spec in self._specs:
            ok = user32.RegisterHotKey(None, spec.id, spec.mods | MOD_NOREPEAT, spec.vk)
            if ok:
                registered.append(spec.id)
            else:
                err = ctypes.get_last_error()
                print(f"[hotkeys] failed to register {spec.name}: err={err}")
        self._ready = True

        msg = wintypes.MSG()
        try:
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                if msg.message == WM_HOTKEY:
                    name = self._id_to_name.get(int(msg.wParam))
                    if name:
                        self.hotkey_fired.emit(name)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hid in registered:
                user32.UnregisterHotKey(None, hid)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


class HotkeyManager(QObject):
    hotkey = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread = HotkeyThread(DEFAULT_HOTKEYS)
        self._thread.hotkey_fired.connect(self.hotkey)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._thread.stop()
        self._thread.wait(1000)
