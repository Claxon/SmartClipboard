from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional


user32 = ctypes.windll.user32


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def _caret_screen_pos() -> Optional[tuple[int, int]]:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    if not tid:
        return None
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
        return None
    rc = gti.rcCaret
    if not gti.hwndCaret:
        return None
    if not (rc.left or rc.top or rc.right or rc.bottom):
        return None
    pt = wintypes.POINT(rc.left, rc.bottom)
    if not user32.ClientToScreen(gti.hwndCaret, ctypes.byref(pt)):
        return None
    return (pt.x, pt.y)


def _cursor_screen_pos() -> Optional[tuple[int, int]]:
    pt = wintypes.POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return (pt.x, pt.y)
    return None


def _foreground_center() -> Optional[tuple[int, int]]:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rc = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return None
    return ((rc.left + rc.right) // 2, (rc.top + rc.bottom) // 2)


def anchor_screen_pos() -> Optional[tuple[int, int]]:
    """Best-effort screen-space point to anchor a popup against: caret > cursor > window center."""
    return _caret_screen_pos() or _cursor_screen_pos() or _foreground_center()


def get_foreground_hwnd() -> int:
    """Return the current foreground window handle (as an int), or 0."""
    return int(user32.GetForegroundWindow() or 0)
