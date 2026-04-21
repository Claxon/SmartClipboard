from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from src.clipboard_monitor import ClipboardMonitor, apply_to_clipboard, item_from_mime
from src.history import HistoryStore
from src.hotkeys import HotkeyManager
from src.paste import send_ctrl_v
from src.ui.history_window import HistoryWindow
from src.ui.popup import CyclingPopup
from src.ui.tray import TrayController


class SmartClipboardApp:
    def __init__(self, qt_app: QApplication):
        self.app = qt_app
        self.app.setQuitOnLastWindowClosed(False)

        self.store = HistoryStore()
        self.monitor = ClipboardMonitor(self.store)
        self.popup = CyclingPopup(self.store)
        self.history_window = HistoryWindow(self.store)
        self.tray = TrayController()
        self.hotkeys = HotkeyManager()

        self.hotkeys.hotkey.connect(self._on_hotkey)
        self.tray.open_history.connect(self.history_window.show_at_cursor)
        self.tray.open_popup.connect(lambda: self.popup.advance(1))
        self.tray.quit_requested.connect(self._quit)

        QTimer.singleShot(0, self._bootstrap_current_clipboard)

        self.hotkeys.start()

    def _bootstrap_current_clipboard(self) -> None:
        cb = QGuiApplication.clipboard()
        item = item_from_mime(cb.mimeData())
        if item is not None:
            self.store.add(item)

    def _on_hotkey(self, name: str) -> None:
        if name == "cycle_popup":
            self.popup.advance(1)
        elif name == "open_history":
            self.history_window.show_at_cursor()
        elif name == "push_secondary":
            items = self.store.items
            if items:
                self.store.push_secondary(items[0])
                self.tray.notify("SmartClipboard", f"Pinned to secondary: {items[0].preview[:60]}")
        elif name == "paste_secondary":
            sec = self.store.secondary
            if not sec:
                self.tray.notify("SmartClipboard", "Secondary buffer is empty — Ctrl+Alt+C to pin.")
                return
            item = sec[0]
            self.monitor.set_ignore_next()
            apply_to_clipboard(item)
            QTimer.singleShot(80, send_ctrl_v)

    def _quit(self) -> None:
        self.hotkeys.stop()
        self.app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SmartClipboard")
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "SmartClipboard", "System tray not available.")
        return 1

    controller = SmartClipboardApp(app)  # noqa: F841
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
