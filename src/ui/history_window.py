from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..clipboard_monitor import apply_to_clipboard
from ..history import HistoryItem, HistoryStore, ItemKind
from .popup import _item_icon, _kind_badge_text
from .theme import APP_STYLE


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


class HistoryWindow(QWidget):
    def __init__(self, store: HistoryStore, parent: QWidget | None = None):
        super().__init__(parent)
        self._store = store
        store.changed.connect(self._refresh)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(APP_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        root = QFrame()
        root.setObjectName("Root")
        outer.addWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Clipboard History")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addStretch(1)
        self._secondary_btn = QPushButton("Send → Secondary")
        self._secondary_btn.clicked.connect(self._on_push_secondary)
        header.addWidget(self._secondary_btn)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._on_clear)
        header.addWidget(clear)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setIconSize(QSize(40, 40))
        self._list.setUniformItemSizes(False)
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemDoubleClicked.connect(self._on_activated)
        layout.addWidget(self._list, 1)

        hint = QLabel("Enter paste · Delete remove · Esc close · Ctrl+Alt+V pastes secondary")
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        self.resize(640, 520)

        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.hide)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self._on_delete)

    def show_at_cursor(self) -> None:
        self._refresh()
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

    def _refresh(self) -> None:
        self._list.clear()
        for item in self._store.items:
            row = HistoryRow(item)
            wi = QListWidgetItem()
            wi.setSizeHint(row.sizeHint())
            wi.setData(Qt.UserRole, item.id)
            self._list.addItem(wi)
            self._list.setItemWidget(wi, row)

    def _selected_item_id(self) -> str | None:
        cur = self._list.currentItem()
        if cur is None:
            return None
        return cur.data(Qt.UserRole)

    def _on_activated(self, _item: QListWidgetItem) -> None:
        iid = self._selected_item_id()
        if not iid:
            return
        item = self._store.get(iid)
        if item is None:
            return
        apply_to_clipboard(item)
        self._store.add(item)
        self.hide()

    def _on_delete(self) -> None:
        iid = self._selected_item_id()
        if iid:
            self._store.remove(iid)

    def _on_push_secondary(self) -> None:
        iid = self._selected_item_id()
        if not iid:
            return
        item = self._store.get(iid)
        if item is None:
            return
        self._store.push_secondary(item)

    def _on_clear(self) -> None:
        self._store.clear()
