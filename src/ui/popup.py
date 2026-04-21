from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..clipboard_monitor import apply_to_clipboard
from ..foreground import anchor_screen_pos
from ..history import HistoryItem, HistoryStore, ItemKind
from .theme import APP_STYLE


AUTO_CONFIRM_MS = 1400
MAX_VISIBLE = 7


def _kind_badge_text(kind: ItemKind) -> str:
    return {ItemKind.TEXT: "TEXT", ItemKind.FILES: "FILES", ItemKind.IMAGE: "IMAGE"}[kind]


def _item_icon(item: HistoryItem, size: int = 40) -> QPixmap:
    if item.kind == ItemKind.IMAGE and item.thumbnail is not None:
        pm = item.thumbnail
        if pm.height() > size or pm.width() > size:
            pm = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return pm
    style = QApplication.style()
    if item.kind == ItemKind.FILES:
        icon = style.standardIcon(QStyle.SP_FileIcon)
    else:
        icon = style.standardIcon(QStyle.SP_FileDialogDetailedView)
    return icon.pixmap(size, size)


class ItemCard(QFrame):
    def __init__(self, item: HistoryItem, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("selected", False)
        self._item = item

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        icon_label = QLabel()
        pm = _item_icon(item)
        icon_label.setPixmap(pm)
        icon_label.setFixedSize(48, 48)
        icon_label.setAlignment(Qt.AlignCenter)
        root.addWidget(icon_label)

        text_wrap = QVBoxLayout()
        text_wrap.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(6)
        badge = QLabel(_kind_badge_text(item.kind))
        badge.setObjectName("KindBadge")
        top.addWidget(badge, 0, Qt.AlignLeft)
        top.addStretch(1)
        text_wrap.addLayout(top)

        body = QLabel(item.preview)
        body.setObjectName("ItemText")
        body.setWordWrap(False)
        fm = QFontMetrics(body.font())
        body.setText(fm.elidedText(item.preview, Qt.ElideRight, 420))
        text_wrap.addWidget(body)

        meta_txt = ""
        if item.kind == ItemKind.FILES and item.files:
            meta_txt = Path(item.files[0]).parent.as_posix()
        elif item.kind == ItemKind.IMAGE and item.image is not None:
            meta_txt = f"{item.image.width()} × {item.image.height()} px"
        if meta_txt:
            meta = QLabel(fm.elidedText(meta_txt, Qt.ElideMiddle, 420))
            meta.setObjectName("ItemMeta")
            text_wrap.addWidget(meta)

        root.addLayout(text_wrap, 1)

    def set_selected(self, value: bool) -> None:
        self.setProperty("selected", "true" if value else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class CyclingPopup(QWidget):
    confirmed = Signal(str)
    cancelled = Signal()

    def __init__(self, store: HistoryStore, parent: QWidget | None = None):
        super().__init__(parent)
        self._store = store
        self._items: list[HistoryItem] = []
        self._selected = 0
        self._cards: list[ItemCard] = []

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet(APP_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        root = QFrame()
        root.setObjectName("Root")
        outer.addWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Clipboard · Cycle")
        title.setObjectName("Title")
        hint = QLabel("Ctrl+/ next · Shift+Ctrl+/ prev · Enter paste · Esc cancel")
        hint.setObjectName("Hint")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(hint)
        layout.addLayout(header)

        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(6)
        layout.addLayout(self._cards_layout)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._auto_confirm)

        self.resize(560, 60)

    def advance(self, step: int = 1) -> None:
        items = self._store.items[:MAX_VISIBLE]
        if not items:
            return
        if not self.isVisible():
            anchor = anchor_screen_pos()
            self._items = items
            self._selected = 0
            self._rebuild()
            self._place_at(anchor)
            self.show()
            self.raise_()
            self.activateWindow()
            self.setFocus(Qt.ActiveWindowFocusReason)
            self._timer.start(AUTO_CONFIRM_MS)
            return
        self._selected = (self._selected + step) % len(self._items)
        self._update_selection()
        self._timer.start(AUTO_CONFIRM_MS)

    def _rebuild(self) -> None:
        while self._cards_layout.count():
            child = self._cards_layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
        self._cards = []
        for item in self._items:
            card = ItemCard(item)
            self._cards.append(card)
            self._cards_layout.addWidget(card)
        self._update_selection()
        self.adjustSize()

    def _update_selection(self) -> None:
        for idx, card in enumerate(self._cards):
            card.set_selected(idx == self._selected)

    def _place_at(self, anchor: tuple[int, int] | None) -> None:
        self.adjustSize()
        w, h = self.width(), self.height()
        if anchor is None:
            screen = QGuiApplication.primaryScreen()
            geo = screen.availableGeometry()
            self.move(geo.x() + (geo.width() - w) // 2, geo.y() + int(geo.height() * 0.25))
            return
        ax, ay = anchor
        screen = QGuiApplication.screenAt(QPoint(ax, ay)) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        # offset: slightly right of and below the caret, like IME/autocomplete popups
        x = ax - 24
        y = ay + 18
        # if we'd clip the bottom, flip above the caret line
        if y + h > geo.y() + geo.height() - 8:
            y = ay - h - 8
        x = max(geo.x() + 8, min(x, geo.x() + geo.width() - w - 8))
        y = max(geo.y() + 8, min(y, geo.y() + geo.height() - h - 8))
        self.move(x, y)

    def _auto_confirm(self) -> None:
        if not self.isVisible():
            return
        self._confirm()

    def _confirm(self) -> None:
        self._timer.stop()
        if self._items and 0 <= self._selected < len(self._items):
            chosen = self._items[self._selected]
            apply_to_clipboard(chosen)
            self._store.add(chosen)
            self.confirmed.emit(chosen.id)
        self.hide()

    def _cancel(self) -> None:
        self._timer.stop()
        self.hide()
        self.cancelled.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key_Escape,):
            self._cancel()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._confirm()
            return
        if key in (Qt.Key_Down, Qt.Key_Tab):
            self.advance(1)
            return
        if key in (Qt.Key_Up, Qt.Key_Backtab):
            self.advance(-1)
            return
        if key == Qt.Key_Slash:
            step = -1 if event.modifiers() & Qt.ShiftModifier else 1
            self.advance(step)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):  # type: ignore[override]
        super().focusOutEvent(event)
        self._cancel()

    def mousePressEvent(self, event) -> None:  # click outside cards = confirm top
        super().mousePressEvent(event)
