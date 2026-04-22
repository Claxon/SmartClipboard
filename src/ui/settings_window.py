from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import DEFAULT_BINDINGS, Config
from ..key_parse import parse_chord
from .theme import APP_STYLE


# Labels shown for each hotkey name
BINDING_LABELS: dict[str, str] = {
    "cycle_popup": "Cycle popup",
    "open_history": "Open history window",
    "push_secondary": "Pin to secondary buffer",
    "paste_secondary": "Paste from secondary buffer",
}


class ChordEdit(QLineEdit):
    """Read-only line edit that captures a keystroke chord when focused."""

    chord_changed = Signal(str)

    def __init__(self, initial: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._chord = initial
        self._render()
        self.setPlaceholderText("Click, then press a chord…")
        self.setMinimumWidth(220)

    def chord(self) -> str:
        return self._chord

    def set_chord(self, chord: str) -> None:
        self._chord = chord
        self._render()

    def _render(self) -> None:
        self.setText(self._chord or "")

    def focusInEvent(self, e) -> None:  # type: ignore[override]
        super().focusInEvent(e)
        if not self._chord:
            self.setText("Press a chord…")

    def focusOutEvent(self, e) -> None:  # type: ignore[override]
        super().focusOutEvent(e)
        self._render()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        # ignore pure-modifier key events
        if key in (
            Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta, Qt.Key_AltGr,
            Qt.Key_CapsLock, Qt.Key_NumLock, Qt.Key_ScrollLock,
        ):
            return
        if key == Qt.Key_Escape:
            self._chord = ""
            self._render()
            self.clearFocus()
            self.chord_changed.emit("")
            return

        mods = event.modifiers()
        parts: list[str] = []
        if mods & Qt.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.AltModifier:
            parts.append("Alt")
        if mods & Qt.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.MetaModifier:
            parts.append("Win")

        main = QKeySequence(key).toString()
        if not main:
            return
        # QKeySequence returns e.g. 'Slash', 'Return', 'F1', 'A'. Prefer short punctuation.
        mapping = {
            "Slash": "/", "Backslash": "\\", "Semicolon": ";", "Apostrophe": "'",
            "BracketLeft": "[", "BracketRight": "]", "Comma": ",", "Period": ".",
            "Minus": "-", "Equal": "=", "QuoteLeft": "`",
        }
        main = mapping.get(main, main)
        parts.append(main)
        self._chord = "+".join(parts)
        self._render()
        self.chord_changed.emit(self._chord)


class SettingsWindow(QWidget):
    saved = Signal(Config)

    def __init__(self, config: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self._config = config.copy()
        self.setWindowTitle("SmartClipboard · Settings")
        self.setStyleSheet(APP_STYLE)
        self.setMinimumWidth(520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)

        root = QFrame()
        root.setObjectName("Root")
        outer.addWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("Settings")
        title.setObjectName("Title")
        layout.addWidget(title)

        # Hotkey rows
        keys_box = QFormLayout()
        keys_box.setSpacing(8)
        self._edits: dict[str, ChordEdit] = {}
        for name in DEFAULT_BINDINGS.keys():
            edit = ChordEdit(self._config.bindings.get(name, DEFAULT_BINDINGS[name]))
            self._edits[name] = edit
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(edit, 1)
            reset = QPushButton("↺")
            reset.setToolTip("Restore default")
            reset.setFixedWidth(32)
            reset.clicked.connect(lambda _=False, n=name: self._reset_binding(n))
            row.addWidget(reset)
            wrap = QWidget()
            wrap.setLayout(row)
            keys_box.addRow(BINDING_LABELS.get(name, name), wrap)
        layout.addLayout(keys_box)

        # Popup timeout
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel("Popup auto-close timer"))
        self._timeout = QSpinBox()
        self._timeout.setRange(200, 60000)
        self._timeout.setSingleStep(100)
        self._timeout.setSuffix(" ms")
        self._timeout.setValue(self._config.popup_timeout_ms)
        timeout_row.addStretch(1)
        timeout_row.addWidget(self._timeout)
        layout.addLayout(timeout_row)

        # Auto-paste
        self._auto_paste = QCheckBox("Immediately paste into the active window on confirm")
        self._auto_paste.setChecked(self._config.auto_paste_on_confirm)
        layout.addWidget(self._auto_paste)

        # Selection buffer
        self._sel_buf = QCheckBox(
            "Auto-capture text selections into the secondary buffer (experimental)"
        )
        self._sel_buf.setChecked(self._config.selection_buffer_enabled)
        layout.addWidget(self._sel_buf)
        sel_hint = QLabel(
            "When on, a drag-selection with the mouse briefly reads the selected text "
            "via Ctrl+C (your primary clipboard is preserved). Ctrl+Alt+V pastes it."
        )
        sel_hint.setObjectName("Hint")
        sel_hint.setWordWrap(True)
        layout.addWidget(sel_hint)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        save = QPushButton("Save")
        save.clicked.connect(self._on_save)
        save.setDefault(True)
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    def _reset_binding(self, name: str) -> None:
        self._edits[name].set_chord(DEFAULT_BINDINGS[name])

    def _on_save(self) -> None:
        new_bindings: dict[str, str] = {}
        errors: list[str] = []
        used: dict[tuple[int, int], str] = {}
        for name, edit in self._edits.items():
            chord = edit.chord().strip()
            if not chord:
                errors.append(f"{BINDING_LABELS[name]} is empty")
                continue
            try:
                mods, vk = parse_chord(chord)
            except ValueError as e:
                errors.append(f"{BINDING_LABELS[name]}: {e}")
                continue
            key = (mods, vk)
            if key in used:
                errors.append(f"{BINDING_LABELS[name]} clashes with {BINDING_LABELS[used[key]]}")
                continue
            used[key] = name
            new_bindings[name] = chord
        if errors:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid settings", "\n".join(errors))
            return

        self._config.bindings = new_bindings
        self._config.popup_timeout_ms = int(self._timeout.value())
        self._config.auto_paste_on_confirm = self._auto_paste.isChecked()
        self._config.selection_buffer_enabled = self._sel_buf.isChecked()
        self._config.save()
        self.saved.emit(self._config)
        self.close()
