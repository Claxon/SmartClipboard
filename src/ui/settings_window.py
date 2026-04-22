from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import DEFAULT_GLOBAL_BINDINGS, Config
from ..history import ALL_KINDS, BufferConfig, ItemKind, make_id
from ..key_parse import parse_chord
from .theme import APP_STYLE


SETTINGS_STYLE = """
QWidget#SettingsRoot { background: #1b1d23; }
QTabWidget::pane { border: 0; background: #1b1d23; }
QTabBar::tab {
    background: transparent; color: #aab1c2;
    padding: 8px 14px; border: 0; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
}
QTabBar::tab:selected { background: #262a34; color: #e9ecf3; }
QTabBar::tab:hover { color: #e9ecf3; }
QGroupBox {
    border: 1px solid #2c303a; border-radius: 10px; margin-top: 12px; padding: 12px 10px 10px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #aab1c2;
}
QListWidget#BufferPicker {
    background: #181a20; border: 1px solid #262a34; border-radius: 10px;
    padding: 6px; outline: 0;
}
QListWidget#BufferPicker::item {
    border: 1px solid transparent; border-radius: 8px;
    padding: 6px 8px; margin: 2px 0;
}
QListWidget#BufferPicker::item:selected { background: #28334a; border: 1px solid #3a5a95; }
"""


BINDING_LABELS: dict[str, str] = {
    "cycle_popup": "Cycle popup",
    "open_history": "Open history window",
}


class ChordEdit(QLineEdit):
    """Read-only line edit that captures a chord on keypress."""

    chord_changed = Signal(str)

    def __init__(self, initial: str = "", allow_empty: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._chord = initial
        self._allow_empty = allow_empty
        self.setPlaceholderText("Click, then press a chord…" if not allow_empty else "none — click to record")
        self._render()
        self.setMinimumWidth(200)

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
        if key == Qt.Key_Backspace and self._allow_empty:
            self._chord = ""
            self._render()
            self.chord_changed.emit("")
            return
        mods = event.modifiers()
        parts: list[str] = []
        if mods & Qt.ControlModifier: parts.append("Ctrl")
        if mods & Qt.AltModifier: parts.append("Alt")
        if mods & Qt.ShiftModifier: parts.append("Shift")
        if mods & Qt.MetaModifier: parts.append("Win")
        main = QKeySequence(key).toString()
        if not main:
            return
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


class BufferEditor(QWidget):
    """Edit form for a single BufferConfig."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._cfg: BufferConfig | None = None
        self._updating = False

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)

        # Basic info
        basic = QFormLayout()
        basic.setSpacing(6)
        self._name = QLineEdit()
        self._name.textEdited.connect(self._emit_change)
        basic.addRow("Name", self._name)

        self._max_items = QSpinBox()
        self._max_items.setRange(1, 5000)
        self._max_items.setValue(200)
        self._max_items.valueChanged.connect(lambda _=0: self._emit_change())
        basic.addRow("Max items", self._max_items)
        v.addLayout(basic)

        # Accepted kinds
        kinds_group = QGroupBox("Accepts")
        kl = QHBoxLayout(kinds_group)
        self._k_text = QCheckBox("Text")
        self._k_files = QCheckBox("Files")
        self._k_image = QCheckBox("Images")
        for cb in (self._k_text, self._k_files, self._k_image):
            cb.toggled.connect(lambda _=False: self._emit_change())
            kl.addWidget(cb)
        kl.addStretch(1)
        v.addWidget(kinds_group)

        # Behaviour
        behave = QGroupBox("Behaviour")
        bl = QVBoxLayout(behave)
        self._track_main = QCheckBox("Track the main clipboard (auto-store matching items)")
        self._track_main.toggled.connect(lambda _=False: self._emit_change())
        bl.addWidget(self._track_main)
        self._auto_sel = QCheckBox("Auto-capture text drag-selections (Linux-style)")
        self._auto_sel.toggled.connect(lambda _=False: self._emit_change())
        bl.addWidget(self._auto_sel)
        v.addWidget(behave)

        # Hotkeys
        keys = QGroupBox("Hotkeys")
        kf = QFormLayout(keys)
        kf.setSpacing(6)
        self._paste = ChordEdit(allow_empty=True)
        self._paste.chord_changed.connect(lambda _: self._emit_change())
        kf.addRow("Paste this buffer", self._paste)
        self._capture = ChordEdit(allow_empty=True)
        self._capture.chord_changed.connect(lambda _: self._emit_change())
        kf.addRow("Copy current clipboard into this buffer", self._capture)
        v.addWidget(keys)

        v.addStretch(1)

        # Delete warning / protected
        self._protected_note = QLabel("The Main buffer is protected — it mirrors the system clipboard.")
        self._protected_note.setObjectName("Hint")
        self._protected_note.setWordWrap(True)
        v.addWidget(self._protected_note)

    def load(self, cfg: BufferConfig) -> None:
        self._updating = True
        self._cfg = cfg
        self._name.setText(cfg.name)
        self._max_items.setValue(cfg.max_items)
        self._k_text.setChecked(ItemKind.TEXT in cfg.accepted_kinds)
        self._k_files.setChecked(ItemKind.FILES in cfg.accepted_kinds)
        self._k_image.setChecked(ItemKind.IMAGE in cfg.accepted_kinds)
        self._track_main.setChecked(cfg.track_main)
        self._auto_sel.setChecked(cfg.auto_capture_selection)
        self._paste.set_chord(cfg.paste_chord or "")
        self._capture.set_chord(cfg.capture_chord or "")
        self._name.setEnabled(not cfg.protected or cfg.id != "main")
        # we still allow Main to be edited in name (cosmetic), but protected from deletion.
        self._protected_note.setVisible(cfg.protected)
        self._updating = False

    def _emit_change(self) -> None:
        if self._updating or self._cfg is None:
            return
        self.changed.emit()

    def read_into(self, cfg: BufferConfig) -> None:
        cfg.name = self._name.text().strip() or cfg.name
        cfg.max_items = int(self._max_items.value())
        kinds: list[ItemKind] = []
        if self._k_text.isChecked(): kinds.append(ItemKind.TEXT)
        if self._k_files.isChecked(): kinds.append(ItemKind.FILES)
        if self._k_image.isChecked(): kinds.append(ItemKind.IMAGE)
        cfg.accepted_kinds = kinds or list(ALL_KINDS)
        cfg.track_main = self._track_main.isChecked()
        cfg.auto_capture_selection = self._auto_sel.isChecked()
        cfg.paste_chord = self._paste.chord().strip()
        cfg.capture_chord = self._capture.chord().strip()


class SettingsWindow(QWidget):
    saved = Signal(Config)

    def __init__(self, config: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self._config = config.copy()
        self.setWindowTitle("SmartClipboard · Settings")
        self.setObjectName("SettingsRoot")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(APP_STYLE + SETTINGS_STYLE)
        self.resize(760, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        root.addWidget(self._tabs, 1)

        self._tabs.addTab(self._build_general_tab(), "General")
        self._tabs.addTab(self._build_buffers_tab(), "Buffers")

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        root.addLayout(btns)

        self._refresh_buffer_list(select_index=0)

    # --- General tab -----

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(12)

        keys = QGroupBox("Global hotkeys")
        kf = QFormLayout(keys)
        kf.setSpacing(6)
        self._global_edits: dict[str, ChordEdit] = {}
        for name in DEFAULT_GLOBAL_BINDINGS.keys():
            edit = ChordEdit(
                self._config.global_bindings.get(name, DEFAULT_GLOBAL_BINDINGS[name]),
                allow_empty=True,
            )
            self._global_edits[name] = edit
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(edit, 1)
            reset = QPushButton("↺")
            reset.setToolTip("Restore default")
            reset.setFixedWidth(32)
            reset.clicked.connect(lambda _=False, n=name: self._global_edits[n].set_chord(DEFAULT_GLOBAL_BINDINGS[n]))
            row.addWidget(reset)
            wrap = QWidget()
            wrap.setLayout(row)
            kf.addRow(BINDING_LABELS.get(name, name), wrap)
        v.addWidget(keys)

        popup = QGroupBox("Cycling popup")
        pf = QFormLayout(popup)
        pf.setSpacing(6)
        self._ctrl_release = QCheckBox("Paste as soon as Ctrl is released")
        self._ctrl_release.setChecked(self._config.ctrl_release_confirms)
        pf.addRow(self._ctrl_release)
        self._auto_paste = QCheckBox("Immediately paste into the active window on confirm")
        self._auto_paste.setChecked(self._config.auto_paste_on_confirm)
        pf.addRow(self._auto_paste)
        self._timeout = QSpinBox()
        self._timeout.setRange(200, 60000)
        self._timeout.setSingleStep(100)
        self._timeout.setSuffix(" ms")
        self._timeout.setValue(self._config.popup_timeout_ms)
        pf.addRow("Auto-close timer", self._timeout)
        v.addWidget(popup)

        sel = QGroupBox("Selection buffer (experimental)")
        sv = QVBoxLayout(sel)
        self._sel_enabled = QCheckBox("Enable auto-capture of text drag-selections")
        self._sel_enabled.setChecked(self._config.selection_buffer_enabled)
        sv.addWidget(self._sel_enabled)
        hint = QLabel(
            "When on, a drag-selection is read via a brief Ctrl+C round-trip "
            "(your primary clipboard is preserved) and stored into any buffer "
            "with “auto-capture text drag-selections” turned on."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        sv.addWidget(hint)
        v.addWidget(sel)

        v.addStretch(1)
        return w

    # --- Buffers tab -----

    def _build_buffers_tab(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(10, 10, 10, 10)
        h.setSpacing(10)

        # Left: picker
        left = QVBoxLayout()
        self._buffer_list = QListWidget()
        self._buffer_list.setObjectName("BufferPicker")
        self._buffer_list.currentRowChanged.connect(self._on_buffer_selected)
        left.addWidget(self._buffer_list, 1)
        toolbar = QHBoxLayout()
        self._add_btn = QPushButton("+ Add buffer")
        self._add_btn.clicked.connect(self._on_add_buffer)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._on_remove_buffer)
        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(self._remove_btn)
        toolbar.addStretch(1)
        left.addLayout(toolbar)
        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(240)
        h.addWidget(left_wrap)

        # Right: editor
        self._editor = BufferEditor()
        self._editor.changed.connect(self._on_editor_changed)
        h.addWidget(self._editor, 1)

        return w

    def _refresh_buffer_list(self, select_index: int | None = None) -> None:
        self._buffer_list.blockSignals(True)
        self._buffer_list.clear()
        for b in self._config.buffers:
            wi = QListWidgetItem(b.name + (" *" if b.protected else ""))
            wi.setData(Qt.UserRole, b.id)
            self._buffer_list.addItem(wi)
        self._buffer_list.blockSignals(False)
        if select_index is None:
            select_index = 0
        if 0 <= select_index < self._buffer_list.count():
            self._buffer_list.setCurrentRow(select_index)
        else:
            self._editor.setEnabled(False)

    def _current_buffer(self) -> BufferConfig | None:
        row = self._buffer_list.currentRow()
        if row < 0 or row >= len(self._config.buffers):
            return None
        return self._config.buffers[row]

    def _on_buffer_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._config.buffers):
            self._editor.setEnabled(False)
            return
        self._editor.setEnabled(True)
        b = self._config.buffers[row]
        self._editor.load(b)
        self._remove_btn.setEnabled(not b.protected)

    def _on_editor_changed(self) -> None:
        b = self._current_buffer()
        if b is None:
            return
        self._editor.read_into(b)
        # refresh label
        row = self._buffer_list.currentRow()
        if row >= 0:
            self._buffer_list.item(row).setText(b.name + (" *" if b.protected else ""))

    def _on_add_buffer(self) -> None:
        new = BufferConfig(
            id=make_id(),
            name="New buffer",
            accepted_kinds=list(ALL_KINDS),
            track_main=True,
            max_items=100,
        )
        self._config.buffers.append(new)
        self._refresh_buffer_list(select_index=len(self._config.buffers) - 1)

    def _on_remove_buffer(self) -> None:
        b = self._current_buffer()
        if b is None or b.protected:
            return
        idx = self._buffer_list.currentRow()
        confirm = QMessageBox.question(
            self, "Remove buffer", f"Remove buffer “{b.name}”?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        self._config.buffers.pop(idx)
        self._refresh_buffer_list(select_index=max(0, idx - 1))

    # --- save -----

    def _on_save(self) -> None:
        # Validate globals
        globals_: dict[str, str] = {}
        errors: list[str] = []
        for name, edit in self._global_edits.items():
            chord = edit.chord().strip()
            if not chord:
                errors.append(f"{BINDING_LABELS.get(name, name)} is required")
                continue
            try:
                parse_chord(chord)
            except ValueError as e:
                errors.append(f"{BINDING_LABELS.get(name, name)}: {e}")
                continue
            globals_[name] = chord

        # Validate buffer chords & gather (ensure current editor changes are read)
        b = self._current_buffer()
        if b is not None:
            self._editor.read_into(b)
        used: dict[tuple[int, int], str] = {}
        for name, chord in globals_.items():
            try:
                mods, vk = parse_chord(chord)
            except ValueError:
                continue
            used[(mods, vk)] = f"Global:{name}"
        for buf in self._config.buffers:
            for field_name, chord in (("paste", buf.paste_chord), ("capture", buf.capture_chord)):
                if not chord:
                    continue
                try:
                    mods, vk = parse_chord(chord)
                except ValueError as e:
                    errors.append(f"{buf.name} · {field_name}: {e}")
                    continue
                if (mods, vk) in used:
                    errors.append(
                        f"{buf.name} · {field_name} clashes with {used[(mods, vk)]}"
                    )
                    continue
                used[(mods, vk)] = f"{buf.name}:{field_name}"

        if errors:
            QMessageBox.warning(self, "Invalid settings", "\n".join(errors))
            return

        self._config.global_bindings = globals_
        self._config.popup_timeout_ms = int(self._timeout.value())
        self._config.auto_paste_on_confirm = self._auto_paste.isChecked()
        self._config.ctrl_release_confirms = self._ctrl_release.isChecked()
        self._config.selection_buffer_enabled = self._sel_enabled.isChecked()
        self._config.save()
        self.saved.emit(self._config)
        self.close()
