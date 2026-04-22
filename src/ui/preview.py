"""Hover preview popover — shows full text / larger image / full file list."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..history import HistoryItem, ItemKind


PREVIEW_W = 520
PREVIEW_H_MAX = 420
IMAGE_BIG = 380


class HoverPreview(QWidget):
    """A frameless on-top popover that shows full content for a HistoryItem."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.ToolTip
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        # A basic dark card style — intentionally self-contained so this works
        # regardless of the parent window's stylesheet quirks.
        self.setStyleSheet(
            """
            QWidget#PreviewRoot {
                background: #23262e;
                border: 1px solid #3a3f4c;
                border-radius: 10px;
            }
            QLabel#PreviewTitle {
                color: #9da4b6;
                font-size: 10px;
                letter-spacing: 0.6px;
                padding: 2px 4px;
            }
            QLabel#PreviewBody {
                color: #e9ecf3;
                font-size: 13px;
                font-family: "Segoe UI Variable", "Segoe UI", system-ui, sans-serif;
            }
            QLabel#PreviewMono {
                color: #e9ecf3;
                font-family: Consolas, "Cascadia Mono", monospace;
                font-size: 12px;
            }
            QScrollArea { background: transparent; border: 0; }
            QScrollBar:vertical { background: transparent; width: 8px; }
            QScrollBar::handle:vertical { background: #3e4453; border-radius: 3px; }
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self._root = QFrame()
        self._root.setObjectName("PreviewRoot")
        outer.addWidget(self._root)

        self._layout = QVBoxLayout(self._root)
        self._layout.setContentsMargins(10, 8, 10, 10)
        self._layout.setSpacing(4)

        self._title = QLabel("")
        self._title.setObjectName("PreviewTitle")
        self._layout.addWidget(self._title)

        self._content_host = QWidget()
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(4)
        self._layout.addWidget(self._content_host, 1)

        self.setMinimumWidth(240)
        self.setMaximumWidth(PREVIEW_W + 20)
        self.resize(PREVIEW_W, 200)
        self.hide()

    def _clear_content(self) -> None:
        while self._content_layout.count():
            child = self._content_layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()

    def show_for(self, item: HistoryItem, anchor_global: QPoint) -> None:
        self._clear_content()
        if item.kind == ItemKind.TEXT:
            self._title.setText("TEXT")
            text = item.text or ""
            lbl = QLabel(text)
            lbl.setObjectName("PreviewMono" if _looks_codey(text) else "PreviewBody")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.NoTextInteraction)
            lbl.setMaximumWidth(PREVIEW_W - 20)
            if len(text) > 1200:
                # Big text — use a scroll area to cap height.
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.NoFrame)
                holder = QWidget()
                hl = QVBoxLayout(holder)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.addWidget(lbl)
                scroll.setWidget(holder)
                scroll.setMaximumHeight(PREVIEW_H_MAX)
                self._content_layout.addWidget(scroll, 1)
            else:
                self._content_layout.addWidget(lbl)
        elif item.kind == ItemKind.FILES:
            self._title.setText(f"FILES · {len(item.files)}")
            # up to ~20 rows; the rest summarised
            max_rows = 20
            for path in item.files[:max_rows]:
                row = QLabel(path)
                row.setObjectName("PreviewMono")
                row.setWordWrap(True)
                self._content_layout.addWidget(row)
            if len(item.files) > max_rows:
                more = QLabel(f"… and {len(item.files) - max_rows} more")
                more.setObjectName("PreviewTitle")
                self._content_layout.addWidget(more)
        elif item.kind == ItemKind.IMAGE and item.image is not None:
            img = item.image
            self._title.setText(f"IMAGE · {img.width()}×{img.height()}")
            pm = QPixmap.fromImage(img)
            if pm.width() > IMAGE_BIG or pm.height() > IMAGE_BIG:
                pm = pm.scaled(IMAGE_BIG, IMAGE_BIG, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl = QLabel()
            lbl.setPixmap(pm)
            lbl.setAlignment(Qt.AlignCenter)
            self._content_layout.addWidget(lbl)

        self.adjustSize()
        self._place_near(anchor_global)
        self.show()
        self.raise_()

    def _place_near(self, anchor: QPoint) -> None:
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = anchor.x() + 16
        y = anchor.y() + 16
        if x + w > geo.x() + geo.width() - 8:
            x = anchor.x() - w - 16
        if y + h > geo.y() + geo.height() - 8:
            y = max(geo.y() + 8, anchor.y() - h - 16)
        x = max(geo.x() + 8, x)
        y = max(geo.y() + 8, y)
        self.move(x, y)


def _looks_codey(text: str) -> bool:
    if "\t" in text or "\n" in text:
        return True
    return False


class HoverTracker(QObject):
    """Attaches hover detection to widgets, showing a HoverPreview for each item.

    A single HoverPreview is shared across trackers so only one can show at once.
    """

    _shared_preview: HoverPreview | None = None
    _active: "HoverTracker | None" = None

    @classmethod
    def shared_preview(cls) -> HoverPreview:
        if cls._shared_preview is None:
            cls._shared_preview = HoverPreview()
        return cls._shared_preview

    @classmethod
    def hide_preview(cls) -> None:
        if cls._shared_preview is not None:
            cls._shared_preview.hide()

    def __init__(self, delay_ms: int = 380):
        super().__init__()
        self._delay = delay_ms
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._pending_item: HistoryItem | None = None
        self._pending_anchor: QPoint = QPoint()

    def schedule(self, item: HistoryItem, anchor_global: QPoint) -> None:
        self._pending_item = item
        self._pending_anchor = anchor_global
        self._timer.start(self._delay)

    def cancel(self) -> None:
        self._timer.stop()
        self._pending_item = None

    def hide_if_current(self) -> None:
        if HoverTracker._active is self:
            HoverTracker.hide_preview()
            HoverTracker._active = None

    def _fire(self) -> None:
        if self._pending_item is None:
            return
        HoverTracker._active = self
        self.shared_preview().show_for(self._pending_item, self._pending_anchor)
