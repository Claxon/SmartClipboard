APP_STYLE = """
* {
    font-family: "Segoe UI Variable", "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
    color: #e6e8ee;
}
QWidget#Root {
    background: #1b1d23;
    border: 1px solid #2c303a;
    border-radius: 14px;
}
QLabel#Title {
    color: #aab1c2;
    font-size: 11px;
    letter-spacing: 0.6px;
    text-transform: uppercase;
    padding: 4px 2px;
}
QLabel#Hint {
    color: #7e8494;
    font-size: 11px;
    padding: 2px;
}
QLabel#ItemText {
    color: #e9ecf3;
    font-size: 14px;
}
QLabel#ItemMeta {
    color: #8a90a2;
    font-size: 11px;
}
QLabel#KindBadge {
    background: #2a2f3a;
    color: #9da4b6;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 10px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
QFrame#Card {
    background: #23262e;
    border: 1px solid #2f333e;
    border-radius: 10px;
}
QFrame#Card[selected="true"] {
    border: 1px solid #6aa3ff;
    background: #28334a;
}
QListWidget {
    background: #181a20;
    border: 1px solid #2c303a;
    border-radius: 10px;
    padding: 6px;
    outline: 0;
}
QListWidget::item {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    margin: 2px 0;
    padding: 6px;
}
QListWidget::item:selected {
    background: #28334a;
    border: 1px solid #3a5a95;
}
QListWidget::item:hover {
    background: #222631;
}
QPushButton {
    background: #2a2f3a;
    color: #e6e8ee;
    border: 1px solid #373c48;
    border-radius: 8px;
    padding: 6px 12px;
}
QPushButton:hover { background: #323846; }
QPushButton:pressed { background: #232834; }
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: #373c48; border-radius: 4px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #4a5162; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
