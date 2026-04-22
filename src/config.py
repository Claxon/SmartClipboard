from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "SmartClipboard" / "config.json"


DEFAULT_BINDINGS: dict[str, str] = {
    "cycle_popup": "Ctrl+/",
    "open_history": "Ctrl+Shift+Alt+V",  # avoid clashing with "paste without formatting"
    "push_secondary": "Ctrl+Alt+C",
    "paste_secondary": "Ctrl+Alt+V",
}


@dataclass
class Config:
    bindings: dict = field(default_factory=lambda: dict(DEFAULT_BINDINGS))
    popup_timeout_ms: int = 1400
    auto_paste_on_confirm: bool = True
    selection_buffer_enabled: bool = False
    selection_min_chars: int = 2

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
        c = cls()
        c.bindings = {**DEFAULT_BINDINGS, **dict(data.get("bindings") or {})}
        c.popup_timeout_ms = int(data.get("popup_timeout_ms", c.popup_timeout_ms))
        c.auto_paste_on_confirm = bool(data.get("auto_paste_on_confirm", c.auto_paste_on_confirm))
        c.selection_buffer_enabled = bool(data.get("selection_buffer_enabled", c.selection_buffer_enabled))
        c.selection_min_chars = int(data.get("selection_min_chars", c.selection_min_chars))
        return c

    def save(self) -> None:
        p = _config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def copy(self) -> "Config":
        return Config(
            bindings=dict(self.bindings),
            popup_timeout_ms=self.popup_timeout_ms,
            auto_paste_on_confirm=self.auto_paste_on_confirm,
            selection_buffer_enabled=self.selection_buffer_enabled,
            selection_min_chars=self.selection_min_chars,
        )
