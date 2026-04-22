from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from src import single_instance
from src.clipboard_monitor import ClipboardMonitor, apply_to_clipboard, item_from_mime
from src.config import Config
from src.history import HistoryStore
from src.hotkeys import HotkeyManager
from src.paste import send_ctrl_v
from src.selection_buffer import SelectionBuffer
from src.ui.history_window import HistoryWindow
from src.ui.popup import CyclingPopup
from src.ui.settings_window import SettingsWindow
from src.ui.tray import TrayController


class SmartClipboardApp:
    def __init__(self, qt_app: QApplication):
        self.app = qt_app
        self.app.setQuitOnLastWindowClosed(False)

        self.config = Config.load()
        self.store = HistoryStore()
        self.monitor = ClipboardMonitor(self.store)
        self.popup = CyclingPopup(self.store, self.config, self.monitor)
        self.history_window = HistoryWindow(self.store, self.config, self.monitor)
        self.tray = TrayController()
        self.tray.update_hotkey_labels(self.config.bindings)
        self.hotkeys = HotkeyManager(self.config.bindings)

        self.selection = SelectionBuffer(
            self.store, self.monitor, min_chars=self.config.selection_min_chars
        )
        self.selection.set_enabled(self.config.selection_buffer_enabled)

        self._settings_window: SettingsWindow | None = None

        self.hotkeys.hotkey.connect(self._on_hotkey)
        self.tray.open_history.connect(self.history_window.show_at_cursor)
        self.tray.open_popup.connect(lambda: self.popup.advance(1))
        self.tray.open_settings.connect(self._open_settings)
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
                self.tray.notify("SmartClipboard", f"Pinned: {items[0].preview[:60]}")
        elif name == "paste_secondary":
            sec = self.store.secondary
            if not sec:
                self.tray.notify("SmartClipboard", "Secondary buffer is empty.")
                return
            item = sec[0]
            self.monitor.set_ignore_next(1)
            apply_to_clipboard(item)
            QTimer.singleShot(80, send_ctrl_v)

    def _open_settings(self) -> None:
        if self._settings_window is not None and self._settings_window.isVisible():
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        w = SettingsWindow(self.config)
        w.saved.connect(self._apply_new_config)
        self._settings_window = w
        w.show()

    def _apply_new_config(self, new_config: Config) -> None:
        self.config = new_config
        # rebind hotkeys at runtime (no restart needed)
        self.hotkeys.rebind(new_config.bindings)
        # propagate settings to components
        self.popup._config = new_config  # timer + auto_paste read live
        self.history_window._config = new_config
        self.selection.set_min_chars(new_config.selection_min_chars)
        self.selection.set_enabled(new_config.selection_buffer_enabled)
        self.tray.update_hotkey_labels(new_config.bindings)
        self.tray.notify("SmartClipboard", "Settings saved.")

    def _quit(self) -> None:
        self.selection.set_enabled(False)
        self.hotkeys.stop()
        self.app.quit()


def main() -> int:
    if not single_instance.acquire():
        # Quiet second-instance exit with a brief toast. We need a QApplication
        # just long enough to show a tray balloon (no window created).
        tmp = QApplication(sys.argv)
        if QSystemTrayIcon.isSystemTrayAvailable():
            from src.ui.tray import _make_icon
            icon = QSystemTrayIcon(_make_icon())
            icon.show()
            icon.showMessage(
                "SmartClipboard",
                "Already running — check the tray icon.",
                QSystemTrayIcon.Information,
                2500,
            )
            QTimer.singleShot(2800, tmp.quit)
            tmp.exec()
        return 0

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
