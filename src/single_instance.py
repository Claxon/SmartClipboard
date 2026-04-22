"""Named-mutex single-instance guard."""
from __future__ import annotations

import ctypes
from ctypes import wintypes


# Use a WinDLL with use_last_error=True so ctypes.get_last_error() is populated.
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.restype = wintypes.BOOL


ERROR_ALREADY_EXISTS = 183

# Keep a module-level handle so the mutex is released only at process exit.
_handle = None


def acquire(name: str = "SmartClipboard_SingleInstance_v1") -> bool:
    """Try to acquire a named mutex. Returns True if we are the first instance."""
    global _handle
    handle = _k32.CreateMutexW(None, True, name)
    err = ctypes.get_last_error()
    if not handle:
        # CreateMutex itself failed (rare: access denied, etc). Fail open.
        return True
    if err == ERROR_ALREADY_EXISTS:
        _k32.CloseHandle(handle)
        return False
    _handle = handle
    return True
