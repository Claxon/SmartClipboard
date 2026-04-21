# SmartClipboard

A lightweight Windows tray app that adds a clipboard history, a cycling-paste
popup anchored to your text caret, and a secondary "selection buffer" —
inspired by Linux's middle-click paste.

## Features

- **Clipboard history** — text, files (with path), and images (with thumbnail)
- **Cycling popup** — `Ctrl+/` opens a popup at the text caret; press again to
  cycle through recent items. Enter (or a short idle timeout) confirms the
  selection and writes it back to the clipboard, ready for `Ctrl+V`.
- **Secondary buffer** — `Ctrl+Alt+C` pins the current clipboard; `Ctrl+Alt+V`
  pastes it directly, leaving your primary clipboard untouched afterwards.
- **Full history window** — `Ctrl+Shift+V`
- **Runs at startup** (optional, toggle in tray menu — no admin required)

## Install

### Portable exe (recommended)

1. Grab `SmartClipboard.exe` from the latest [release](../../releases/latest).
2. Put it anywhere (e.g. `%LOCALAPPDATA%\SmartClipboard\`) and double-click.
3. Right-click the tray icon → *Run at startup* to auto-launch on login.

### From source

Requires Python 3.10+.

```
install.bat     # creates .venv, installs deps
run.bat         # launches in background via pythonw
```

## Hotkeys

| Chord          | Action                                              |
|----------------|-----------------------------------------------------|
| `Ctrl+/`       | Cycling popup — press again to advance              |
| `Ctrl+Shift+V` | Full history window                                 |
| `Ctrl+Alt+C`   | Pin current clipboard to the secondary buffer       |
| `Ctrl+Alt+V`   | Paste the secondary buffer (sends Ctrl+V for you)   |

Inside the popup: `Enter` confirms · `Esc` cancels · `↑/↓` or `Tab/Shift+Tab`
cycle · `Shift+Ctrl+/` cycles backwards.

## Build the exe yourself

```
install.bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller smartclipboard.spec
# → dist\SmartClipboard.exe
```

## License

MIT
