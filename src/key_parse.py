"""Parse chord strings like 'Ctrl+Shift+/' into Win32 (mods, vk) pairs."""
from __future__ import annotations


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008


MOD_ALIASES: dict[str, int] = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "meta": MOD_WIN,
    "super": MOD_WIN,
}


# Canonical label → VK
_BASE_VK: dict[str, int] = {
    "/": 0xBF, "?": 0xBF,
    "\\": 0xDC, "|": 0xDC,
    ";": 0xBA, ":": 0xBA,
    "'": 0xDE, '"': 0xDE,
    "[": 0xDB, "{": 0xDB,
    "]": 0xDD, "}": 0xDD,
    ",": 0xBC, "<": 0xBC,
    ".": 0xBE, ">": 0xBE,
    "`": 0xC0, "~": 0xC0,
    "-": 0xBD, "_": 0xBD,
    "=": 0xBB, "+": 0xBB,
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pageup": 0x21,
    "pgdn": 0x22, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}

for i in range(26):
    _BASE_VK[chr(ord("a") + i)] = 0x41 + i
for i in range(10):
    _BASE_VK[str(i)] = 0x30 + i
for i in range(1, 13):
    _BASE_VK[f"f{i}"] = 0x70 + (i - 1)


VK_LABELS: dict[int, str] = {}
for label, vk in _BASE_VK.items():
    # Prefer the most user-friendly label when multiple labels share a VK.
    if vk not in VK_LABELS or len(label) > len(VK_LABELS[vk]):
        continue
    VK_LABELS[vk] = label
# Overwrite with "nicer" labels
for vk, label in list(VK_LABELS.items()):
    pass  # initial population done; we'll rebuild below for cleanliness

_PREFERRED: dict[int, str] = {
    0xBF: "/", 0xDC: "\\", 0xBA: ";", 0xDE: "'",
    0xDB: "[", 0xDD: "]", 0xBC: ",", 0xBE: ".",
    0xC0: "`", 0xBD: "-", 0xBB: "=",
    0x20: "Space", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
    0x08: "Backspace", 0x2E: "Delete", 0x2D: "Insert",
    0x24: "Home", 0x23: "End", 0x21: "PgUp", 0x22: "PgDn",
    0x26: "Up", 0x28: "Down", 0x25: "Left", 0x27: "Right",
}
for i in range(26):
    _PREFERRED[0x41 + i] = chr(ord("A") + i)
for i in range(10):
    _PREFERRED[0x30 + i] = str(i)
for i in range(1, 13):
    _PREFERRED[0x70 + (i - 1)] = f"F{i}"


def parse_chord(chord: str) -> tuple[int, int]:
    if not chord or not chord.strip():
        raise ValueError("empty chord")
    parts = [p.strip().lower() for p in chord.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"unparseable chord: {chord!r}")
    mods = 0
    vk = 0
    for p in parts:
        if p in MOD_ALIASES:
            mods |= MOD_ALIASES[p]
        elif p in _BASE_VK:
            vk = _BASE_VK[p]
        else:
            raise ValueError(f"unknown key {p!r} in {chord!r}")
    if vk == 0:
        raise ValueError(f"chord {chord!r} needs a non-modifier key")
    return mods, vk


def format_chord(mods: int, vk: int) -> str:
    parts: list[str] = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    parts.append(_PREFERRED.get(vk, f"VK_{vk:#x}"))
    return "+".join(parts)
