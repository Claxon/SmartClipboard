from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal

from .key_parse import parse_chord


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_REBIND = 0x8001  # our custom thread-message; payload fetched via attribute+lock


@dataclass
class HotkeySpec:
    id: int
    mods: int
    vk: int
    name: str


def specs_from_bindings(bindings: dict[str, str]) -> list[HotkeySpec]:
    """Convert a {name: chord} map into registerable specs. Skips unparseable entries."""
    specs: list[HotkeySpec] = []
    next_id = 1
    for name, chord in bindings.items():
        try:
            mods, vk = parse_chord(chord)
        except ValueError as e:
            print(f"[hotkeys] skipping {name}: {e}")
            continue
        specs.append(HotkeySpec(id=next_id, mods=mods, vk=vk, name=name))
        next_id += 1
    return specs


class HotkeyThread(QThread):
    hotkey_fired = Signal(str)

    def __init__(self, specs: list[HotkeySpec]):
        super().__init__()
        self._current_specs = list(specs)
        self._thread_id = 0
        self._id_to_name: dict[int, str] = {}
        self._pending_lock = threading.Lock()
        self._pending_specs: list[HotkeySpec] | None = None

    def run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._apply_registrations(self._current_specs)

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
                elif msg.message == WM_APP_REBIND:
                    with self._pending_lock:
                        specs = self._pending_specs
                        self._pending_specs = None
                    if specs is not None:
                        self._apply_registrations(specs)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._unregister_all()

    def _apply_registrations(self, specs: list[HotkeySpec]) -> None:
        self._unregister_all()
        self._id_to_name = {}
        for spec in specs:
            ok = user32.RegisterHotKey(None, spec.id, spec.mods | MOD_NOREPEAT, spec.vk)
            if ok:
                self._id_to_name[spec.id] = spec.name
            else:
                err = ctypes.get_last_error()
                print(f"[hotkeys] failed to register {spec.name}: err={err}")
        self._current_specs = list(specs)

    def _unregister_all(self) -> None:
        for hid in list(self._id_to_name.keys()):
            user32.UnregisterHotKey(None, hid)
        self._id_to_name = {}

    def rebind(self, specs: list[HotkeySpec]) -> None:
        with self._pending_lock:
            self._pending_specs = list(specs)
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_APP_REBIND, 0, 0)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


class HotkeyManager(QObject):
    hotkey = Signal(str)

    def __init__(self, bindings: dict[str, str], parent: QObject | None = None):
        super().__init__(parent)
        self._thread = HotkeyThread(specs_from_bindings(bindings))
        self._thread.hotkey_fired.connect(self.hotkey)

    def start(self) -> None:
        self._thread.start()

    def rebind(self, bindings: dict[str, str]) -> None:
        self._thread.rebind(specs_from_bindings(bindings))

    def stop(self) -> None:
        self._thread.stop()
        self._thread.wait(1000)
