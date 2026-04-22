from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QMimeData, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QClipboard, QGuiApplication, QImage, QPixmap

from .history import HistoryItem, HistoryStore, ItemKind, make_id, now


THUMB_SIZE = 96


def _thumbnail_for(image: QImage, size: int = THUMB_SIZE) -> QPixmap:
    if image.isNull():
        return QPixmap()
    pm = QPixmap.fromImage(image)
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def item_from_mime(mime: QMimeData) -> Optional[HistoryItem]:
    if mime is None:
        return None
    if mime.hasImage():
        img = mime.imageData()
        if isinstance(img, QImage) and not img.isNull():
            item = HistoryItem(
                id=make_id(), kind=ItemKind.IMAGE, timestamp=now(), image=img
            )
            item.thumbnail = _thumbnail_for(img)
            return item
    if mime.hasUrls():
        urls = mime.urls()
        files = [u.toLocalFile() for u in urls if u.isLocalFile()]
        files = [f for f in files if f]
        if files:
            return HistoryItem(
                id=make_id(), kind=ItemKind.FILES, timestamp=now(), files=files
            )
    if mime.hasText():
        txt = mime.text()
        if txt and txt.strip():
            return HistoryItem(
                id=make_id(), kind=ItemKind.TEXT, timestamp=now(), text=txt
            )
    return None


def apply_to_clipboard(item: HistoryItem, mode: QClipboard.Mode = QClipboard.Clipboard) -> None:
    cb = QGuiApplication.clipboard()
    mime = QMimeData()
    if item.kind == ItemKind.TEXT and item.text is not None:
        mime.setText(item.text)
    elif item.kind == ItemKind.FILES and item.files:
        mime.setUrls([QUrl.fromLocalFile(f) for f in item.files])
    elif item.kind == ItemKind.IMAGE and item.image is not None:
        mime.setImageData(item.image)
    else:
        return
    cb.setMimeData(mime, mode)


class ClipboardMonitor(QObject):
    item_captured = Signal(HistoryItem)

    def __init__(self, store: HistoryStore, parent: QObject | None = None):
        super().__init__(parent)
        self._store = store
        self._ignore_count = 0
        cb = QGuiApplication.clipboard()
        cb.dataChanged.connect(self._on_changed)

    def set_ignore_next(self, count: int = 1) -> None:
        self._ignore_count += max(0, count)

    def read_current(self) -> HistoryItem | None:
        cb = QGuiApplication.clipboard()
        return item_from_mime(cb.mimeData())

    def _on_changed(self) -> None:
        if self._ignore_count > 0:
            self._ignore_count -= 1
            return
        cb = QGuiApplication.clipboard()
        mime = cb.mimeData()
        item = item_from_mime(mime)
        if item is None:
            return
        self._store.capture_from_main(item)
        self.item_captured.emit(item)
