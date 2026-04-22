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


ALL_KINDS: frozenset[ItemKind] = frozenset({ItemKind.TEXT, ItemKind.FILES, ItemKind.IMAGE})


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


# --- Buffer model -----------------------------------------------------------


@dataclass
class BufferConfig:
    id: str
    name: str = "Buffer"
    accepted_kinds: list[ItemKind] = field(default_factory=lambda: list(ALL_KINDS))
    track_main: bool = True  # auto-mirror items that the main clipboard captures
    max_items: int = 200
    paste_chord: str = ""      # hotkey that pastes this buffer's head
    capture_chord: str = ""    # hotkey that copies the current primary clipboard into this buffer
    auto_capture_selection: bool = False  # receive drag-selected text from the mouse hook
    protected: bool = False    # if True, cannot be deleted from UI (used for "main")

    def accepts(self, item: HistoryItem) -> bool:
        return item.kind in self.accepted_kinds


def make_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()


def default_buffer_configs() -> list[BufferConfig]:
    return [
        BufferConfig(
            id="main",
            name="Main",
            accepted_kinds=list(ALL_KINDS),
            track_main=True,
            max_items=200,
            protected=True,
        ),
        BufferConfig(
            id="selection",
            name="Selection",
            accepted_kinds=[ItemKind.TEXT],
            track_main=False,
            max_items=50,
            paste_chord="Ctrl+Alt+V",
            capture_chord="Ctrl+Alt+C",
            auto_capture_selection=True,
        ),
    ]


class Buffer:
    """One clipboard buffer's contents."""

    def __init__(self, cfg: BufferConfig):
        self.config = cfg
        self._items: list[HistoryItem] = []

    @property
    def items(self) -> list[HistoryItem]:
        return list(self._items)

    def head(self) -> Optional[HistoryItem]:
        return self._items[0] if self._items else None

    def accepts(self, item: HistoryItem) -> bool:
        return self.config.accepts(item)

    def add(self, item: HistoryItem) -> bool:
        if self._items and self._items[0].signature() == item.signature():
            return False
        for existing in list(self._items):
            if existing.signature() == item.signature():
                self._items.remove(existing)
                break
        self._items.insert(0, item)
        if len(self._items) > max(1, self.config.max_items):
            self._items = self._items[: self.config.max_items]
        return True

    def remove(self, item_id: str) -> None:
        self._items = [i for i in self._items if i.id != item_id]

    def clear(self) -> None:
        self._items.clear()


class HistoryStore(QObject):
    """Holds an ordered collection of Buffers keyed by id."""

    changed = Signal(str)  # buffer id that changed, or "" for structural changes

    def __init__(self, configs: list[BufferConfig] | None = None):
        super().__init__()
        self._buffers: dict[str, Buffer] = {}
        for cfg in (configs or default_buffer_configs()):
            self._buffers[cfg.id] = Buffer(cfg)

    # --- structural -----

    @property
    def buffers(self) -> list[Buffer]:
        return list(self._buffers.values())

    def get(self, buffer_id: str) -> Optional[Buffer]:
        return self._buffers.get(buffer_id)

    def add_buffer(self, cfg: BufferConfig) -> Buffer:
        if cfg.id in self._buffers:
            # update config in place and return the existing Buffer
            self._buffers[cfg.id].config = cfg
            self.changed.emit("")
            return self._buffers[cfg.id]
        buf = Buffer(cfg)
        self._buffers[cfg.id] = buf
        self.changed.emit("")
        return buf

    def remove_buffer(self, buffer_id: str) -> bool:
        buf = self._buffers.get(buffer_id)
        if buf is None or buf.config.protected:
            return False
        del self._buffers[buffer_id]
        self.changed.emit("")
        return True

    def replace_configs(self, configs: list[BufferConfig]) -> None:
        """Replace the buffer set with new configs, keeping items for ids that persist."""
        old = self._buffers
        new: dict[str, Buffer] = {}
        for cfg in configs:
            if cfg.id in old:
                buf = old[cfg.id]
                buf.config = cfg
                new[cfg.id] = buf
            else:
                new[cfg.id] = Buffer(cfg)
        self._buffers = new
        self.changed.emit("")

    # --- item flow -----

    def capture_from_main(self, item: HistoryItem) -> None:
        """Called when the system clipboard changes. Routes to tracking buffers."""
        for buf in self._buffers.values():
            if buf.config.track_main and buf.accepts(item):
                if buf.add(item):
                    self.changed.emit(buf.config.id)

    def capture_selection(self, item: HistoryItem) -> None:
        """Called by the drag-selection hook. Routes to auto-capture buffers."""
        for buf in self._buffers.values():
            if buf.config.auto_capture_selection and buf.accepts(item):
                if buf.add(item):
                    self.changed.emit(buf.config.id)

    def add_to(self, buffer_id: str, item: HistoryItem) -> bool:
        buf = self._buffers.get(buffer_id)
        if buf is None or not buf.accepts(item):
            return False
        ok = buf.add(item)
        if ok:
            self.changed.emit(buffer_id)
        return ok

    def remove_item(self, buffer_id: str, item_id: str) -> None:
        buf = self._buffers.get(buffer_id)
        if buf is None:
            return
        buf.remove(item_id)
        self.changed.emit(buffer_id)

    def clear_buffer(self, buffer_id: str) -> None:
        buf = self._buffers.get(buffer_id)
        if buf is None:
            return
        buf.clear()
        self.changed.emit(buffer_id)

    def find_item(self, item_id: str) -> tuple[Optional[str], Optional[HistoryItem]]:
        for bid, buf in self._buffers.items():
            for it in buf.items:
                if it.id == item_id:
                    return bid, it
        return None, None
