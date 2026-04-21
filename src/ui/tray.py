from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap, QColor, QFont, QBrush, Qt
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QApplication

from .. import startup


def _make_icon() -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QBrush(QColor("#6aa3ff")))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 28, 28, 7, 7)
    p.setPen(QColor("#0d1117"))
    font = QFont("Segoe UI", 14, QFont.Bold)
    p.setFont(font)
    p.drawText(pm.rect(), Qt.AlignCenter, "C")
    p.end()
    return QIcon(pm)


class TrayController(QObject):
    open_history = Signal()
    open_popup = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.tray = QSystemTrayIcon(_make_icon(), parent)
        self.tray.setToolTip("SmartClipboard")

        menu = QMenu()
        act_history = QAction("Open history (Ctrl+Shift+V)", menu)
        act_history.triggered.connect(self.open_history)
        menu.addAction(act_history)

        act_popup = QAction("Cycle popup (Ctrl+/)", menu)
        act_popup.triggered.connect(self.open_popup)
        menu.addAction(act_popup)

        menu.addSeparator()

        self.act_startup = QAction("Run at startup", menu)
        self.act_startup.setCheckable(True)
        self.act_startup.setChecked(startup.is_enabled())
        self.act_startup.toggled.connect(self._on_startup_toggled)
        menu.addAction(self.act_startup)

        menu.addSeparator()
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self.quit_requested)
        menu.addAction(act_quit)

        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.open_history.emit()

    def _on_startup_toggled(self, checked: bool) -> None:
        try:
            if checked:
                startup.enable()
            else:
                startup.disable()
        except Exception as e:
            self.tray.showMessage("SmartClipboard", f"Startup change failed: {e}")

    def notify(self, title: str, message: str) -> None:
        self.tray.showMessage(title, message, QSystemTrayIcon.Information, 2000)
