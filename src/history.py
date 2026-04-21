from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap


class ItemKind(str, Enum):
    TEXT = "text"
    FILES = "files"
    IMAGE = "image"


@dataclass
class HistoryItem:
    id: str
    kind: ItemKind
    timestamp: float
    text: Optional[str] = None
    files: list[str] = field(default_factory=list)
    image: Optional[QImage] = None
    thumbnail: Optional[QPixmap] = None

    @property
    def preview(self) -> str:
        if self.kind == ItemKind.TEXT:
            t = (self.text or "").strip().replace("\r", "")
            single = " ".join(t.split("\n"))
            return single[:120] + ("…" if len(single) > 120 else "")
        if self.kind == ItemKind.FILES:
            if len(self.files) == 1:
                return self.files[0]
            return f"{len(self.files)} files — {Path(self.files[0]).name}, …"
        if self.kind == ItemKind.IMAGE and self.image is not None:
            return f"Image {self.image.width()}×{self.image.height()}"
        return "(empty)"

    def signature(self) -> tuple:
        if self.kind == ItemKind.TEXT:
            return (ItemKind.TEXT, self.text)
        if self.kind == ItemKind.FILES:
            return (ItemKind.FILES, tuple(self.files))
        if self.kind == ItemKind.IMAGE and self.image is not None:
            return (
                ItemKind.IMAGE,
                self.image.width(),
                self.image.height(),
                bytes(self.image.constBits())[:4096],
            )
        return (self.kind,)


class HistoryStore(QObject):
    changed = Signal()

    def __init__(self, max_items: int = 200, secondary_max: int = 20):
        super().__init__()
        self._items: list[HistoryItem] = []
        self._max = max_items
        self._secondary: list[HistoryItem] = []
        self._secondary_max = secondary_max

    @property
    def items(self) -> list[HistoryItem]:
        return list(self._items)

    @property
    def secondary(self) -> list[HistoryItem]:
        return list(self._secondary)

    def add(self, item: HistoryItem) -> bool:
        if self._items and self._items[0].signature() == item.signature():
            return False
        for existing in list(self._items):
            if existing.signature() == item.signature():
                self._items.remove(existing)
                break
        self._items.insert(0, item)
        if len(self._items) > self._max:
            self._items = self._items[: self._max]
        self.changed.emit()
        return True

    def remove(self, item_id: str) -> None:
        self._items = [i for i in self._items if i.id != item_id]
        self.changed.emit()

    def clear(self) -> None:
        self._items.clear()
        self.changed.emit()

    def push_secondary(self, item: HistoryItem) -> None:
        self._secondary.insert(0, item)
        if len(self._secondary) > self._secondary_max:
            self._secondary = self._secondary[: self._secondary_max]
        self.changed.emit()

    def get(self, item_id: str) -> Optional[HistoryItem]:
        for i in self._items:
            if i.id == item_id:
                return i
        for i in self._secondary:
            if i.id == item_id:
                return i
        return None


def make_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()
