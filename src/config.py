from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .history import ALL_KINDS, BufferConfig, ItemKind, default_buffer_configs


def _config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "SmartClipboard" / "config.json"


DEFAULT_GLOBAL_BINDINGS: dict[str, str] = {
    "cycle_popup": "Ctrl+/",
    "open_history": "Ctrl+Shift+Alt+V",
}


@dataclass
class Config:
    global_bindings: dict = field(default_factory=lambda: dict(DEFAULT_GLOBAL_BINDINGS))
    buffers: list[BufferConfig] = field(default_factory=default_buffer_configs)
    popup_timeout_ms: int = 1400
    auto_paste_on_confirm: bool = True
    ctrl_release_confirms: bool = True
    selection_buffer_enabled: bool = False
    selection_min_chars: int = 2

    # --- serialisation -----

    def to_dict(self) -> dict:
        return {
            "global_bindings": dict(self.global_bindings),
            "buffers": [_buffer_to_dict(b) for b in self.buffers],
            "popup_timeout_ms": self.popup_timeout_ms,
            "auto_paste_on_confirm": self.auto_paste_on_confirm,
            "ctrl_release_confirms": self.ctrl_release_confirms,
            "selection_buffer_enabled": self.selection_buffer_enabled,
            "selection_min_chars": self.selection_min_chars,
        }

    @classmethod
    def load(cls) -> "Config":
        p = _config_path()
        if not p.exists():
            c = cls()
            c.save()
            return c
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        c = cls()
        c.global_bindings = _migrate_bindings(data)
        c.buffers = _load_buffers(data)
        c.popup_timeout_ms = int(data.get("popup_timeout_ms", c.popup_timeout_ms))
        c.auto_paste_on_confirm = bool(data.get("auto_paste_on_confirm", c.auto_paste_on_confirm))
        c.ctrl_release_confirms = bool(data.get("ctrl_release_confirms", c.ctrl_release_confirms))
        c.selection_buffer_enabled = bool(data.get("selection_buffer_enabled", c.selection_buffer_enabled))
        c.selection_min_chars = int(data.get("selection_min_chars", c.selection_min_chars))
        return c

    def save(self) -> None:
        p = _config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def copy(self) -> "Config":
        return Config._from_dict(self.to_dict())


# --- helpers ---------------------------------------------------------------


def _buffer_to_dict(b: BufferConfig) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "accepted_kinds": [k.value for k in b.accepted_kinds],
        "track_main": b.track_main,
        "max_items": b.max_items,
        "paste_chord": b.paste_chord,
        "capture_chord": b.capture_chord,
        "auto_capture_selection": b.auto_capture_selection,
        "protected": b.protected,
    }


def _buffer_from_dict(d: dict) -> BufferConfig:
    kinds_raw = d.get("accepted_kinds") or [k.value for k in ALL_KINDS]
    try:
        kinds = [ItemKind(k) for k in kinds_raw if k in {ItemKind.TEXT.value, ItemKind.FILES.value, ItemKind.IMAGE.value}]
    except Exception:
        kinds = list(ALL_KINDS)
    if not kinds:
        kinds = list(ALL_KINDS)
    return BufferConfig(
        id=str(d.get("id") or "buf"),
        name=str(d.get("name") or "Buffer"),
        accepted_kinds=kinds,
        track_main=bool(d.get("track_main", True)),
        max_items=int(d.get("max_items", 200)),
        paste_chord=str(d.get("paste_chord") or ""),
        capture_chord=str(d.get("capture_chord") or ""),
        auto_capture_selection=bool(d.get("auto_capture_selection", False)),
        protected=bool(d.get("protected", False)),
    )


def _load_buffers(data: dict) -> list[BufferConfig]:
    buf_list = data.get("buffers")
    if isinstance(buf_list, list) and buf_list:
        loaded = [_buffer_from_dict(b) for b in buf_list]
        # ensure "main" always exists and is protected
        ids = {b.id for b in loaded}
        if "main" not in ids:
            loaded.insert(0, default_buffer_configs()[0])
        else:
            for b in loaded:
                if b.id == "main":
                    b.protected = True
        return loaded
    # No buffer list → build defaults, then apply any legacy bindings
    buffers = default_buffer_configs()
    legacy = data.get("bindings") or {}
    if legacy:
        for b in buffers:
            if b.id == "selection":
                b.paste_chord = legacy.get("paste_secondary", b.paste_chord)
                b.capture_chord = legacy.get("push_secondary", b.capture_chord)
    return buffers


def _migrate_bindings(data: dict) -> dict[str, str]:
    """Extract global bindings, migrating legacy 'bindings' dicts."""
    globals_ = dict(DEFAULT_GLOBAL_BINDINGS)
    live = data.get("global_bindings")
    if isinstance(live, dict):
        for k, v in live.items():
            if isinstance(v, str):
                globals_[k] = v
        return globals_
    legacy = data.get("bindings")
    if isinstance(legacy, dict):
        for k in ("cycle_popup", "open_history"):
            v = legacy.get(k)
            if isinstance(v, str):
                globals_[k] = v
    return globals_


def hotkey_map(config: Config) -> dict[str, str]:
    """Flattened {hotkey_name: chord} for the HotkeyManager.

    Names used:
      - "cycle_popup", "open_history" (global)
      - "paste:<buffer_id>" for each per-buffer paste chord
      - "capture:<buffer_id>" for each per-buffer capture chord
    """
    out: dict[str, str] = {}
    for k, v in config.global_bindings.items():
        if v:
            out[k] = v
    for b in config.buffers:
        if b.paste_chord:
            out[f"paste:{b.id}"] = b.paste_chord
        if b.capture_chord:
            out[f"capture:{b.id}"] = b.capture_chord
    return out
