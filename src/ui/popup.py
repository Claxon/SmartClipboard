from __future__ import annotations

import ctypes
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, Signal
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

from ..clipboard_monitor import ClipboardMonitor, apply_to_clipboard
from ..config import Config
from ..foreground import anchor_screen_pos, get_foreground_hwnd
from ..history import HistoryItem, HistoryStore, ItemKind
from ..paste import paste_to
from .preview import HoverTracker
from .theme import APP_STYLE


user32 = ctypes.windll.user32
VK_CONTROL = 0x11


def _is_ctrl_down() -> bool:
    return bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)


MAX_VISIBLE = 8
CARD_H = 64
CANCEL_H = 36
CARD_SPACING = 6
POPUP_W = 560


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
    clicked = Signal()
    hovered = Signal(object)  # HistoryItem | None

    def __init__(self, item: HistoryItem, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("selected", False)
        self._item = item
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFixedHeight(CARD_H)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        icon_label = QLabel()
        icon_label.setPixmap(_item_icon(item))
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

    def item(self) -> HistoryItem:
        return self._item

    def set_selected(self, value: bool) -> None:
        self.setProperty("selected", "true" if value else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self.hovered.emit(self._item)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self.hovered.emit(None)
        super().leaveEvent(event)


class CancelCard(QFrame):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("CancelCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(CANCEL_H)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        lbl = QLabel("✕  Cancel")
        lbl.setObjectName("CancelLabel")
        lay.addWidget(lbl)
        lay.addStretch(1)

        hint = QLabel("release Ctrl or click")
        hint.setObjectName("Hint")
        lay.addWidget(hint)

    def set_selected(self, value: bool) -> None:
        self.setProperty("selected", "true" if value else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class CyclingPopup(QWidget):
    confirmed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        store: HistoryStore,
        config: Config,
        monitor: ClipboardMonitor | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._store = store
        self._config = config
        self._monitor = monitor
        self._items: list[HistoryItem] = []
        self._selected = 0
        self._cards: list[ItemCard] = []
        self._cancel_card: CancelCard | None = None
        self._target_hwnd: int = 0
        self._ctrl_mode = False  # opened with Ctrl held → confirm on release
        self._hover_tracker = HoverTracker()
        self._current_buffer_id = "main"

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
        header.setSpacing(8)
        self._title_lbl = QLabel("Clipboard")
        self._title_lbl.setObjectName("Title")
        self._buffer_lbl = QLabel("")
        self._buffer_lbl.setObjectName("BufferBadge")
        self._hint = QLabel("release Ctrl to paste · Esc cancel")
        self._hint.setObjectName("Hint")
        header.addWidget(self._title_lbl)
        header.addWidget(self._buffer_lbl)
        header.addStretch(1)
        header.addWidget(self._hint)
        layout.addLayout(header)

        # Fixed-height cards area so the popup doesn't resize when buffers /
        # item counts change. Items pack at the top, the Cancel row pins to
        # the bottom, and any empty space is pushed between them by a stretch.
        self._cards_host = QWidget()
        self._cards_host.setObjectName("CardsHost")
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(CARD_SPACING)
        cards_h = (
            MAX_VISIBLE * CARD_H
            + (MAX_VISIBLE - 1) * CARD_SPACING
            + CARD_SPACING
            + CANCEL_H
        )
        self._cards_host.setFixedHeight(cards_h)
        layout.addWidget(self._cards_host)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._auto_confirm)

        self._ctrl_timer = QTimer(self)
        self._ctrl_timer.setInterval(25)
        self._ctrl_timer.timeout.connect(self._poll_ctrl)

        # Lock the overall popup size. Height = chrome + cards area; anything
        # that used to call adjustSize() is now a no-op.
        chrome_h = 18 * 2 + 14 * 2 + 22 + 8  # outer, root padding, header, layout spacing
        self.setFixedSize(POPUP_W, cards_h + chrome_h)

    # --- show/advance -----

    def _timeout_ms(self) -> int:
        return max(200, int(self._config.popup_timeout_ms))

    def _total(self) -> int:
        return len(self._items) + 1  # +1 for the cancel row

    def _buffer_ids(self) -> list[str]:
        return [b.config.id for b in self._store.buffers]

    def _load_buffer(self, buffer_id: str) -> None:
        """Snapshot items from the given buffer (or Main as fallback)."""
        buf = self._store.get(buffer_id) or self._store.get("main")
        if buf is None:
            self._items = []
            self._current_buffer_id = buffer_id
            self._buffer_lbl.setText("")
            return
        self._current_buffer_id = buf.config.id
        self._items = buf.items[:MAX_VISIBLE]
        self._selected = 0
        # Header badge shows the buffer name + arrows hint if multiple exist.
        total_buffers = len(self._buffer_ids())
        if total_buffers > 1:
            self._buffer_lbl.setText(f"◀  {buf.config.name}  ▶")
        else:
            self._buffer_lbl.setText(buf.config.name)

    def advance(self, step: int = 1) -> None:
        if not self.isVisible():
            self._target_hwnd = get_foreground_hwnd()
            anchor = anchor_screen_pos()
            self._load_buffer("main")
            # if Main is empty, fall through and show empty state (user can
            # still press Left/Right to a buffer that has items, or Esc/Cancel)
            self._ctrl_mode = bool(self._config.ctrl_release_confirms and _is_ctrl_down())
            self._hint.setText(self._hint_text())
            self._rebuild()
            self._place_at(anchor)
            self.show()
            self.raise_()
            self.activateWindow()
            self.setFocus(Qt.ActiveWindowFocusReason)
            if self._ctrl_mode:
                self._ctrl_timer.start()
            else:
                self._timer.start(self._timeout_ms())
            return
        total = self._total()
        if total == 0:
            return
        self._selected = (self._selected + step) % total
        self._update_selection()
        if not self._ctrl_mode:
            self._timer.start(self._timeout_ms())

    def switch_buffer(self, step: int = 1) -> None:
        """Cycle to the previous/next buffer (left/right arrows)."""
        ids = self._buffer_ids()
        if not ids:
            return
        if self._current_buffer_id in ids:
            idx = ids.index(self._current_buffer_id)
        else:
            idx = 0
        new_idx = (idx + step) % len(ids)
        self._load_buffer(ids[new_idx])
        self._rebuild()
        self._place_at(anchor_screen_pos())
        if not self._ctrl_mode:
            self._timer.start(self._timeout_ms())

    def _hint_text(self) -> str:
        multi = len(self._buffer_ids()) > 1
        arrow_hint = " · ←→ buffer" if multi else ""
        if self._ctrl_mode:
            return f"release Ctrl to paste · Esc cancel{arrow_hint}"
        return f"Enter paste · Esc cancel · click to select{arrow_hint}"

    # --- rendering -----

    def _rebuild(self) -> None:
        while self._cards_layout.count():
            child = self._cards_layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
            # Spacers (returned by QLayoutItem) are also torn down here;
            # takeAt() removes them from the layout.
        self._cards = []
        for idx, item in enumerate(self._items):
            card = ItemCard(item)
            card.clicked.connect(lambda i=idx: self._on_card_clicked(i))
            card.hovered.connect(self._on_card_hover)
            self._cards.append(card)
            self._cards_layout.addWidget(card)
        # Stretch fills whatever vertical space remains, keeping Cancel pinned
        # to the bottom and items packed at the top regardless of item count.
        self._cards_layout.addStretch(1)
        self._cancel_card = CancelCard()
        self._cancel_card.clicked.connect(self._cancel)
        self._cards_layout.addWidget(self._cancel_card)
        self._update_selection()

    def _on_card_clicked(self, idx: int) -> None:
        self._selected = idx
        self._update_selection()
        self._confirm()

    def _on_card_hover(self, item) -> None:
        if item is None:
            self._hover_tracker.cancel()
            self._hover_tracker.hide_if_current()
            return
        # compute anchor near the cursor
        pos = QGuiApplication.screens()[0].geometry().topLeft() if False else None  # dummy
        from PySide6.QtGui import QCursor
        self._hover_tracker.schedule(item, QCursor.pos())

    def _update_selection(self) -> None:
        for idx, card in enumerate(self._cards):
            card.set_selected(idx == self._selected)
        if self._cancel_card is not None:
            self._cancel_card.set_selected(self._selected == len(self._items))

    def _place_at(self, anchor: tuple[int, int] | None) -> None:
        # Size is fixed via setFixedSize in __init__; no adjustSize needed.
        w, h = self.width(), self.height()
        if anchor is None:
            screen = QGuiApplication.primaryScreen()
            geo = screen.availableGeometry()
            self.move(geo.x() + (geo.width() - w) // 2, geo.y() + int(geo.height() * 0.25))
            return
        ax, ay = anchor
        screen = QGuiApplication.screenAt(QPoint(ax, ay)) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = ax - 24
        y = ay + 18
        if y + h > geo.y() + geo.height() - 8:
            y = ay - h - 8
        x = max(geo.x() + 8, min(x, geo.x() + geo.width() - w - 8))
        y = max(geo.y() + 8, min(y, geo.y() + geo.height() - h - 8))
        self.move(x, y)

    # --- input -----

    def _poll_ctrl(self) -> None:
        if not self.isVisible():
            self._ctrl_timer.stop()
            return
        if not _is_ctrl_down():
            self._ctrl_timer.stop()
            if self._selected == len(self._items):
                self._cancel()
            else:
                self._confirm()

    def _auto_confirm(self) -> None:
        if not self.isVisible():
            return
        if self._ctrl_mode:
            # in ctrl-release mode the timer is only used until the user moves;
            # don't auto-confirm while they're still holding Ctrl.
            if _is_ctrl_down():
                return
        if self._selected == len(self._items):
            self._cancel()
        else:
            self._confirm()

    def _confirm(self) -> None:
        self._timer.stop()
        self._ctrl_timer.stop()
        self._hover_tracker.cancel()
        self._hover_tracker.hide_if_current()
        if not (self._items and 0 <= self._selected < len(self._items)):
            self.hide()
            return
        chosen = self._items[self._selected]
        if self._monitor is not None:
            self._monitor.set_ignore_next(1)
        apply_to_clipboard(chosen)
        # Re-insert into the source buffer (bubbles to top via dedup).
        self._store.add_to(self._current_buffer_id, chosen)
        self.confirmed.emit(chosen.id)
        target = self._target_hwnd
        self.hide()
        if self._config.auto_paste_on_confirm and target:
            QTimer.singleShot(30, lambda: paste_to(target))

    def _cancel(self) -> None:
        self._timer.stop()
        self._ctrl_timer.stop()
        self._hover_tracker.cancel()
        self._hover_tracker.hide_if_current()
        self.hide()
        self.cancelled.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        if key == Qt.Key_Escape:
            self._cancel()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._confirm() if self._selected < len(self._items) else self._cancel()
            return
        if key in (Qt.Key_Down, Qt.Key_Tab):
            self.advance(1)
            return
        if key in (Qt.Key_Up, Qt.Key_Backtab):
            self.advance(-1)
            return
        if key == Qt.Key_Right:
            self.switch_buffer(1)
            return
        if key == Qt.Key_Left:
            self.switch_buffer(-1)
            return
        if key == Qt.Key_Slash:
            step = -1 if event.modifiers() & Qt.ShiftModifier else 1
            self.advance(step)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):  # type: ignore[override]
        super().focusOutEvent(event)
        # In ctrl-release mode we don't want to cancel on focus loss because Qt
        # occasionally thinks we lost focus during the show+activate dance.
        if not self._ctrl_mode:
            self._cancel()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._hover_tracker.cancel()
        self._hover_tracker.hide_if_current()
        super().hideEvent(event)
