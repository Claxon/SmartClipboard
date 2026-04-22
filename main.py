from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from src import single_instance
from src.clipboard_monitor import ClipboardMonitor, apply_to_clipboard, item_from_mime
from src.config import Config, hotkey_map
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
        self.store = HistoryStore(configs=self.config.buffers)
        self.monitor = ClipboardMonitor(self.store)
        self.popup = CyclingPopup(self.store, self.config, self.monitor)
        self.history_window = HistoryWindow(self.store, self.config, self.monitor)
        self.tray = TrayController()
        self.tray.update_hotkey_labels(self.config.global_bindings)
        self.hotkeys = HotkeyManager(hotkey_map(self.config))

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
            self.store.capture_from_main(item)

    def _on_hotkey(self, name: str) -> None:
        if name == "cycle_popup":
            self.popup.advance(1)
            return
        if name == "open_history":
            self.history_window.show_at_cursor()
            return
        if name.startswith("paste:"):
            bid = name.split(":", 1)[1]
            self._paste_from_buffer(bid)
            return
        if name.startswith("capture:"):
            bid = name.split(":", 1)[1]
            self._capture_current_into(bid)
            return

    def _paste_from_buffer(self, bid: str) -> None:
        buf = self.store.get(bid)
        if buf is None:
            return
        head = buf.head()
        if head is None:
            self.tray.notify("SmartClipboard", f"{buf.config.name} is empty.")
            return
        self.monitor.set_ignore_next(1)
        apply_to_clipboard(head)
        QTimer.singleShot(80, send_ctrl_v)

    def _capture_current_into(self, bid: str) -> None:
        buf = self.store.get(bid)
        if buf is None:
            return
        item = self.monitor.read_current()
        if item is None:
            self.tray.notify("SmartClipboard", "Clipboard is empty.")
            return
        if not buf.accepts(item):
            kinds = ", ".join(k.value for k in buf.config.accepted_kinds)
            self.tray.notify("SmartClipboard", f"{buf.config.name} only accepts: {kinds}")
            return
        self.store.add_to(bid, item)
        self.tray.notify("SmartClipboard", f"Copied to {buf.config.name}: {item.preview[:60]}")

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
        # Rebuild store's buffer set (preserves items for persisted ids)
        self.store.replace_configs(new_config.buffers)
        # Rebind hotkeys live
        self.hotkeys.rebind(hotkey_map(new_config))
        # Propagate to components
        self.popup._config = new_config
        self.history_window._config = new_config
        self.selection.set_min_chars(new_config.selection_min_chars)
        self.selection.set_enabled(new_config.selection_buffer_enabled)
        self.tray.update_hotkey_labels(new_config.global_bindings)
        self.tray.notify("SmartClipboard", "Settings saved.")

    def _quit(self) -> None:
        self.selection.set_enabled(False)
        self.hotkeys.stop()
        self.app.quit()


def main() -> int:
    if not single_instance.acquire():
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
