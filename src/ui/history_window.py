from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..clipboard_monitor import ClipboardMonitor, apply_to_clipboard
from ..config import Config
from ..foreground import get_foreground_hwnd
from ..history import Buffer, HistoryItem, HistoryStore, ItemKind
from ..paste import paste_to
from .popup import _item_icon, _kind_badge_text
from .preview import HoverTracker
from .theme import APP_STYLE


HISTORY_STYLE = """
QWidget#HistoryRoot {
    background: #1b1d23;
}
QTabWidget::pane {
    border: 0;
    background: #1b1d23;
}
QTabBar::tab {
    background: transparent;
    color: #aab1c2;
    padding: 8px 14px;
    border: 0;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabBar::tab:selected {
    background: #262a34;
    color: #e9ecf3;
}
QTabBar::tab:hover { color: #e9ecf3; }

QListWidget#BufferList {
    background: #181a20;
    border: 0;
    padding: 6px;
    outline: 0;
}
QListWidget#BufferList::item {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    margin: 2px 0;
    padding: 6px;
}
QListWidget#BufferList::item:selected {
    background: #28334a;
    border: 1px solid #3a5a95;
}
QListWidget#BufferList::item:hover {
    background: #222631;
}
"""


class HistoryRow(QWidget):
    def __init__(self, item: HistoryItem, parent: QWidget | None = None):
        super().__init__(parent)
        self._item = item

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        icon_label = QLabel()
        icon_label.setFixedSize(44, 44)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(_item_icon(item, 40))
        layout.addWidget(icon_label)

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
        text_wrap.addWidget(body)

        if item.kind == ItemKind.FILES and item.files:
            meta = QLabel(Path(item.files[0]).parent.as_posix())
            meta.setObjectName("ItemMeta")
            text_wrap.addWidget(meta)
        elif item.kind == ItemKind.IMAGE and item.image is not None:
            meta = QLabel(f"{item.image.width()} × {item.image.height()} px")
            meta.setObjectName("ItemMeta")
            text_wrap.addWidget(meta)

        layout.addLayout(text_wrap, 1)


class BufferTab(QWidget):
    """One tab — a list of items for a single buffer, plus actions."""

    def __init__(
        self,
        buffer_id: str,
        store: HistoryStore,
        on_activate,  # callable(HistoryItem)
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._buffer_id = buffer_id
        self._store = store
        self._on_activate = on_activate
        self._hover_tracker = HoverTracker()

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self._meta_lbl = QLabel("")
        self._meta_lbl.setObjectName("Hint")
        toolbar.addWidget(self._meta_lbl)
        toolbar.addStretch(1)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._on_clear)
        toolbar.addWidget(self._clear_btn)
        v.addLayout(toolbar)

        self._list = QListWidget()
        self._list.setObjectName("BufferList")
        self._list.setIconSize(QSize(40, 40))
        self._list.setUniformItemSizes(False)
        self._list.setMouseTracking(True)
        self._list.itemActivated.connect(self._activate_item)
        self._list.itemDoubleClicked.connect(self._activate_item)
        self._list.itemEntered.connect(self._on_item_hover)
        self._list.viewport().installEventFilter(self)
        v.addWidget(self._list, 1)

        self._empty_lbl = QLabel("Nothing here yet.")
        self._empty_lbl.setObjectName("Hint")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(self._empty_lbl)

        self.refresh()

    # Hover
    def eventFilter(self, obj, event):  # type: ignore[override]
        if obj is self._list.viewport():
            if event.type().name in ("Leave",):
                self._hover_tracker.cancel()
                self._hover_tracker.hide_if_current()
        return super().eventFilter(obj, event)

    def _on_item_hover(self, wi: QListWidgetItem) -> None:
        iid = wi.data(Qt.UserRole)
        buf = self._store.get(self._buffer_id)
        if buf is None:
            return
        for it in buf.items:
            if it.id == iid:
                self._hover_tracker.schedule(it, QCursor.pos())
                return

    def buffer_id(self) -> str:
        return self._buffer_id

    def refresh(self) -> None:
        buf = self._store.get(self._buffer_id)
        self._list.clear()
        if buf is None:
            self._meta_lbl.setText("(missing)")
            self._empty_lbl.setVisible(True)
            return
        for item in buf.items:
            row = HistoryRow(item)
            wi = QListWidgetItem()
            wi.setSizeHint(row.sizeHint())
            wi.setData(Qt.UserRole, item.id)
            self._list.addItem(wi)
            self._list.setItemWidget(wi, row)
        kinds = ", ".join(k.value for k in buf.config.accepted_kinds)
        track = "tracks main" if buf.config.track_main else "manual"
        self._meta_lbl.setText(f"{len(buf.items)} · {kinds} · {track}")
        self._empty_lbl.setVisible(len(buf.items) == 0)
        self._clear_btn.setEnabled(len(buf.items) > 0)

    def _on_clear(self) -> None:
        self._store.clear_buffer(self._buffer_id)

    def current_item_id(self) -> str | None:
        cur = self._list.currentItem()
        if cur is None:
            return None
        return cur.data(Qt.UserRole)

    def _activate_item(self, _item: QListWidgetItem | None = None) -> None:
        iid = self.current_item_id()
        if not iid:
            return
        buf = self._store.get(self._buffer_id)
        if buf is None:
            return
        for it in buf.items:
            if it.id == iid:
                self._on_activate(it)
                return

    def activate_current(self) -> None:
        self._activate_item()

    def delete_current(self) -> None:
        iid = self.current_item_id()
        if iid:
            self._store.remove_item(self._buffer_id, iid)


class HistoryWindow(QWidget):
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
        self._target_hwnd: int = 0

        self.setWindowTitle("Clipboard · History")
        # Normal decorated window (no frameless/translucent). Keeps a real
        # resizable border and taskbar presence. The narrow 1px colored border
        # that used to ring the content is gone.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("HistoryRoot")
        self.setStyleSheet(APP_STYLE + HISTORY_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setTabsClosable(False)
        root.addWidget(self._tabs, 1)

        hint = QLabel("Enter paste · Delete remove · Esc close · hover for preview")
        hint.setObjectName("Hint")
        hint.setContentsMargins(12, 4, 12, 8)
        root.addWidget(hint)

        self.resize(760, 560)

        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.hide)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self._on_delete)
        QShortcut(QKeySequence(Qt.Key_Return), self, activated=self._activate_current)
        QShortcut(QKeySequence(Qt.Key_Enter), self, activated=self._activate_current)

        self._store.changed.connect(self._on_store_changed)
        self._rebuild_tabs()

    # --- tabs -----

    def _rebuild_tabs(self) -> None:
        current_id = self._current_buffer_id()
        self._tabs.blockSignals(True)
        while self._tabs.count():
            w = self._tabs.widget(0)
            self._tabs.removeTab(0)
            w.deleteLater()
        for buf in self._store.buffers:
            tab = BufferTab(buf.config.id, self._store, self._activate_item)
            title = buf.config.name
            if len(buf.items):
                title = f"{buf.config.name}  ({len(buf.items)})"
            self._tabs.addTab(tab, title)
        self._tabs.blockSignals(False)
        if current_id:
            self._select_tab_by_buffer_id(current_id)

    def _select_tab_by_buffer_id(self, bid: str) -> None:
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if isinstance(w, BufferTab) and w.buffer_id() == bid:
                self._tabs.setCurrentIndex(i)
                return

    def _current_buffer_id(self) -> str | None:
        w = self._tabs.currentWidget()
        if isinstance(w, BufferTab):
            return w.buffer_id()
        return None

    def _on_store_changed(self, buffer_id: str) -> None:
        if not buffer_id:
            self._rebuild_tabs()
            return
        # update just the affected tab title + content
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if isinstance(w, BufferTab) and w.buffer_id() == buffer_id:
                w.refresh()
                buf = self._store.get(buffer_id)
                if buf is not None:
                    title = buf.config.name + (f"  ({len(buf.items)})" if buf.items else "")
                    self._tabs.setTabText(i, title)
                return

    # --- show -----

    def show_at_cursor(self) -> None:
        self._rebuild_tabs()
        self._target_hwnd = get_foreground_hwnd()
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        # focus the current tab's list for immediate keyboard use
        cur = self._tabs.currentWidget()
        if isinstance(cur, BufferTab) and cur._list.count() > 0 and cur._list.currentRow() < 0:
            cur._list.setCurrentRow(0)

    # --- actions -----

    def _activate_current(self) -> None:
        w = self._tabs.currentWidget()
        if isinstance(w, BufferTab):
            w.activate_current()

    def _on_delete(self) -> None:
        w = self._tabs.currentWidget()
        if isinstance(w, BufferTab):
            w.delete_current()

    def _activate_item(self, item: HistoryItem) -> None:
        target = self._target_hwnd
        if self._monitor is not None:
            self._monitor.set_ignore_next(1)
        apply_to_clipboard(item)
        self._store.add_to("main", item)
        self.hide()
        from PySide6.QtCore import QTimer
        if self._config.auto_paste_on_confirm and target:
            QTimer.singleShot(30, lambda: paste_to(target))
