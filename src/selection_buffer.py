"""Linux-style selection buffer for Windows.

Approach (best-effort, opt-in):
1. Install a WH_MOUSE_LL global hook.
2. On LBUTTONDOWN, remember the point. On LBUTTONUP, if the pointer moved more
   than a few pixels, assume a drag-select happened.
3. Save current clipboard, synthesize Ctrl+C, wait a tick for the clipboard to
   update, read the new text into the secondary buffer, then restore the saved
   clipboard.

Guard rails:
- If our own window is the foreground, do nothing (avoids loops in settings).
- If a modifier is held during the mouse-up (Ctrl/Alt/Shift/Win) we skip —
  likely a modifier-click, not a selection end.
- Track an in-flight flag so concurrent selections don't stack.
- Ignore the clipboard round-trip in ClipboardMonitor via counter-based ignore.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from .clipboard_monitor import ClipboardMonitor, apply_to_clipboard, item_from_mime
from .history import HistoryItem, HistoryStore, ItemKind, make_id, now
from .paste import send_ctrl_c


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

VK_CONTROL = 0x11
VK_MENU = 0x12
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


def _is_modifier_held() -> bool:
    for vk in (VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN):
        if user32.GetAsyncKeyState(vk) & 0x8000:
            return True
    return False


def _our_window_foreground() -> bool:
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
    return int(pid.value) == int(kernel32.GetCurrentProcessId())


class SelectionBuffer(QObject):
    captured = Signal(str)

    def __init__(
        self,
        store: HistoryStore,
        monitor: ClipboardMonitor,
        min_chars: int = 2,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._store = store
        self._monitor = monitor
        self._min_chars = max(1, min_chars)

        self._enabled = False
        self._hook_handle = None
        # keep a strong reference to the HOOKPROC callback — if gc'd while
        # installed we'd get a crash inside user32.
        self._hook_proc = HOOKPROC(self._on_mouse_event)

        self._down_pt: tuple[int, int] | None = None
        self._in_flight = False
        self._saved_item: HistoryItem | None = None

    def set_min_chars(self, n: int) -> None:
        self._min_chars = max(1, int(n))

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled and not self._enabled:
            self._install_hook()
        elif not enabled and self._enabled:
            self._remove_hook()
        self._enabled = enabled

    def _install_hook(self) -> None:
        hmod = kernel32.GetModuleHandleW(None)
        handle = user32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_proc, hmod, 0)
        if not handle:
            err = ctypes.get_last_error()
            print(f"[selection] SetWindowsHookExW failed: {err}")
            return
        self._hook_handle = handle

    def _remove_hook(self) -> None:
        if self._hook_handle:
            user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None
        self._down_pt = None

    # runs on the thread that installed the hook (our main thread, inside Qt's message pump).
    # MUST return quickly — heavy work is deferred via QTimer.singleShot.
    def _on_mouse_event(self, nCode: int, wParam: int, lParam: int) -> int:
        try:
            if nCode >= 0:
                info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT))[0]
                if wParam == WM_LBUTTONDOWN:
                    self._down_pt = (info.pt.x, info.pt.y)
                elif wParam == WM_LBUTTONUP and self._down_pt is not None:
                    dx = info.pt.x - self._down_pt[0]
                    dy = info.pt.y - self._down_pt[1]
                    self._down_pt = None
                    if dx * dx + dy * dy >= 16:  # moved > ~4px → probably a drag select
                        # defer the actual capture so the hook returns fast
                        QTimer.singleShot(30, self._maybe_capture)
        except Exception as e:
            print(f"[selection] hook error: {e}")
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _maybe_capture(self) -> None:
        if self._in_flight:
            return
        if _our_window_foreground():
            return
        if _is_modifier_held():
            return
        self._in_flight = True
        # preserve whatever is on the clipboard right now
        self._saved_item = self._monitor.read_current()
        # the Ctrl+C write will fire one dataChanged we don't want to capture
        self._monitor.set_ignore_next(1)
        send_ctrl_c()
        QTimer.singleShot(120, self._read_after_copy)

    def _read_after_copy(self) -> None:
        try:
            cb = QGuiApplication.clipboard()
            text = cb.text()
            if text and len(text.strip()) >= self._min_chars:
                item = HistoryItem(id=make_id(), kind=ItemKind.TEXT, timestamp=now(), text=text)
                self._store.capture_selection(item)
                self.captured.emit(text)
        finally:
            # restore prior clipboard contents (if any) — this fires another dataChanged
            if self._saved_item is not None:
                self._monitor.set_ignore_next(1)
                apply_to_clipboard(self._saved_item)
            self._saved_item = None
            self._in_flight = False
