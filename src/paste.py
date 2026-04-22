from __future__ import annotations

import ctypes
from ctypes import wintypes


user32 = ctypes.windll.user32

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_V = 0x56
VK_C = 0x43


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def _make_input(vk: int, flags: int) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(vk, 0, flags, 0, None)
    return inp


def _send_chord(main_vk: int) -> None:
    seq = [
        _make_input(VK_MENU, KEYEVENTF_KEYUP),
        _make_input(VK_SHIFT, KEYEVENTF_KEYUP),
        _make_input(VK_LWIN, KEYEVENTF_KEYUP),
        _make_input(VK_RWIN, KEYEVENTF_KEYUP),
        _make_input(VK_CONTROL, KEYEVENTF_KEYUP),
        _make_input(VK_CONTROL, 0),
        _make_input(main_vk, 0),
        _make_input(main_vk, KEYEVENTF_KEYUP),
        _make_input(VK_CONTROL, KEYEVENTF_KEYUP),
    ]
    arr = (INPUT * len(seq))(*seq)
    user32.SendInput(len(seq), ctypes.byref(arr), ctypes.sizeof(INPUT))


def send_ctrl_v() -> None:
    """Release held modifiers, then synthesize Ctrl+V."""
    _send_chord(VK_V)


def send_ctrl_c() -> None:
    """Release held modifiers, then synthesize Ctrl+C."""
    _send_chord(VK_C)


def restore_focus(hwnd: int) -> bool:
    """Bring the given hwnd back to the foreground. Best-effort."""
    if not hwnd:
        return False
    try:
        user32.SwitchToThisWindow(hwnd, True)
    except Exception:
        pass
    return bool(user32.SetForegroundWindow(hwnd))


def paste_to(hwnd: int) -> None:
    """Restore focus to hwnd and fire Ctrl+V."""
    restore_focus(hwnd)
    # Give the foreground change a tick to settle before synthesizing input.
    # A small sleep here is acceptable — caller is already off the UI thread path
    # by virtue of being triggered from a click/keypress handler.
    import time
    time.sleep(0.04)
    send_ctrl_v()
