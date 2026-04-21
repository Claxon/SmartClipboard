# SmartClipboard — project notes

Windows-only tray app that extends the system clipboard with history, a
cycling-paste popup, and a secondary "selection buffer".

## Architecture

Single-process Qt app. The event loop in `main.py` owns everything; there is no
IPC. One auxiliary Win32 thread exists for the hotkey message pump.

```
main.py
└── SmartClipboardApp
    ├── HistoryStore           (src/history.py) — dedup ring buffer: primary (200) + secondary (20)
    ├── ClipboardMonitor       (src/clipboard_monitor.py) — QClipboard.dataChanged → HistoryItem
    ├── CyclingPopup           (src/ui/popup.py) — frameless Qt.Tool window, caret-anchored
    ├── HistoryWindow          (src/ui/history_window.py) — full list, Enter pastes, Delete removes
    ├── TrayController         (src/ui/tray.py) — QSystemTrayIcon + menu + startup toggle
    └── HotkeyManager          (src/hotkeys.py) — dedicated thread running GetMessage pump
        └── RegisterHotKey → WM_HOTKEY → Qt signal

helpers:
  src/foreground.py   — caret/cursor/window-rect lookup via GetGUIThreadInfo
  src/paste.py        — SendInput Ctrl+V synthesis (releases held modifiers first)
  src/startup.py      — HKCU\...\Run registry toggle
  src/ui/theme.py     — QSS
```

## Hotkey contract (Win32 VK codes, see `src/hotkeys.py`)

| Chord          | Action            | Notes                                                    |
|----------------|-------------------|----------------------------------------------------------|
| Ctrl+/         | cycle_popup       | first press opens at item 0; subsequent presses advance  |
| Ctrl+Shift+V   | open_history      | full list window                                         |
| Ctrl+Alt+C     | push_secondary    | pin current primary clipboard into secondary buffer      |
| Ctrl+Alt+V     | paste_secondary   | swap clipboard → SendInput Ctrl+V; no restore            |

Hotkeys are registered with `MOD_NOREPEAT` against `hwnd=NULL`, so WM_HOTKEY
posts to the registering thread's queue — that thread is `HotkeyThread` and is
dedicated to the message pump. To stop it: `PostThreadMessageW(tid, WM_QUIT)`.

## Clipboard capture semantics

`ClipboardMonitor` listens to `QClipboard.dataChanged` and calls
`item_from_mime()` which prefers, in order: image → urls (files) → text. This
ordering matters: a screenshot often carries both image and text (OCR'd path);
we want the image.

Dedup: `HistoryStore.add()` compares `HistoryItem.signature()` — a tuple of
`(kind, payload-or-bytes-prefix)`. If incoming == head, no-op; if incoming
matches any older entry, that older entry is removed and the new one inserted
at the top.

`ClipboardMonitor.set_ignore_next()` is the flag used when *we* write the
clipboard (e.g. Ctrl+Alt+V path) so the write doesn't round-trip into history.

## Popup positioning

`src/foreground.py::anchor_screen_pos()` returns the first success of:
1. `GetGUIThreadInfo(tid).rcCaret` → `ClientToScreen` on the foreground window
2. `GetCursorPos`
3. `GetWindowRect` center

Many Chromium/Electron apps don't expose a system caret — those fall through
to cursor. `CyclingPopup._place_at()` offsets slightly below-right of the
anchor, flips above the caret if it would clip the bottom, and clamps to the
`QScreen.availableGeometry()` of whichever screen contains the anchor.

## Non-obvious gotchas

- **Ctrl+Alt+V modifier stuck-keys.** When the hotkey fires, the user is still
  holding Alt (and Ctrl). Before synthesizing Ctrl+V we inject KEYUPs for
  VK_MENU, VK_SHIFT, VK_LWIN/RWIN, VK_CONTROL. See `src/paste.py::send_ctrl_v`.
- **Virtual keycode for `/`.** It's `VK_OEM_2 = 0xBF` on US layouts. Other
  layouts may break this binding.
- **QSystemTrayIcon.isSystemTrayAvailable()** is checked at startup; we abort
  with a message box if false (some locked-down sessions have no tray).
- **QClipboard on Windows** fires `dataChanged` via an internal
  `AddClipboardFormatListener`; we don't register one ourselves.
- **`setQuitOnLastWindowClosed(False)`** is essential — both popup and history
  window can be hidden simultaneously and the app must stay alive for hotkeys.

## Running / building

```
install.bat              # creates .venv, pip install -r requirements.txt
run.bat                  # launches via pythonw (no console)
py -m PyInstaller smartclipboard.spec   # builds portable exe into dist/
```

The exe is a single-file PyInstaller build (`--onefile --windowed`). No admin
privileges required — `RegisterHotKey` and `HKCU\...\Run` both work as a
standard user.

## Changing hotkeys

Edit `DEFAULT_HOTKEYS` in `src/hotkeys.py`. There is no settings file yet; a
future change would load from JSON at startup. Register before calling
`HotkeyManager.start()` — the pump thread builds the registration table in
`HotkeyThread.run()` before entering the message loop.
