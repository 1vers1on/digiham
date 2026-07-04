"""A modern dark theme: a Fusion palette plus a hand-tuned stylesheet.

Colours are collected in :data:`PALETTE` so the decode tables and the
waterfall can reuse the exact accents used by the chrome.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Central colour tokens (also used by widgets for decode highlighting).
PALETTE = {
    "bg":          "#14171c",
    "bg_alt":      "#181c22",
    "panel":       "#1e232b",
    "panel_hi":    "#252b34",
    "border":      "#2c333d",
    "text":        "#e6e9ef",
    "text_dim":    "#98a1b0",
    "accent":      "#4c8dff",
    "accent_dim":  "#2d5cad",
    "green":       "#39d98a",
    "amber":       "#ffb454",
    "red":         "#ff5c6c",
    "cyan":        "#3ad0e0",
    "magenta":     "#c678dd",
    # decode row highlight backgrounds
    "hl_cq":       "#173a2a",   # a CQ call
    "hl_tome":     "#3a2140",   # addressed to my call
    "hl_newcall":  "#1c3350",   # a station I haven't worked
    "tx":          "#5a1a20",   # transmitting indicator
}


def _c(key: str) -> QColor:
    return QColor(PALETTE[key])


def apply_theme(app: QApplication, font_size: int = 11) -> None:
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, _c("bg"))
    pal.setColor(QPalette.ColorRole.WindowText, _c("text"))
    pal.setColor(QPalette.ColorRole.Base, _c("bg_alt"))
    pal.setColor(QPalette.ColorRole.AlternateBase, _c("panel"))
    pal.setColor(QPalette.ColorRole.Text, _c("text"))
    pal.setColor(QPalette.ColorRole.Button, _c("panel"))
    pal.setColor(QPalette.ColorRole.ButtonText, _c("text"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, _c("panel_hi"))
    pal.setColor(QPalette.ColorRole.ToolTipText, _c("text"))
    pal.setColor(QPalette.ColorRole.Highlight, _c("accent"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Link, _c("accent"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, _c("text_dim"))
    disabled = _c("text_dim")
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    app.setPalette(pal)

    app.setStyleSheet(_STYLESHEET.format(fs=font_size, **PALETTE))


_STYLESHEET = """
* {{ font-size: {fs}pt; }}
QWidget {{ color: {text}; }}
QMainWindow, QDialog {{ background: {bg}; }}

QGroupBox {{
    border: 1px solid {border};
    border-radius: 8px;
    margin-top: 14px;
    padding: 8px 8px 8px 8px;
    background: {panel};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {text_dim};
    font-weight: 600;
}}

QPushButton {{
    background: {panel_hi};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 5px 12px;
}}
QPushButton:hover {{ background: #2c343f; border-color: {accent_dim}; }}
QPushButton:pressed {{ background: {accent_dim}; }}
QPushButton:checked {{ background: {accent_dim}; border-color: {accent}; }}
QPushButton:disabled {{ background: {panel}; color: {text_dim}; }}

QPushButton#txButton:checked {{ background: {tx}; border-color: {red}; }}
QPushButton#cqButton {{ font-weight: 600; }}

QComboBox, QSpinBox, QLineEdit, QDoubleSpinBox {{
    background: {bg_alt};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {accent};
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: {accent_dim}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {panel};
    border: 1px solid {border};
    selection-background-color: {accent_dim};
    outline: none;
}}

QLabel#dialLabel {{
    font-size: {fs}pt;
    color: {text_dim};
}}
QLabel#bigFreq {{
    font-family: "DejaVu Sans Mono", monospace;
    font-weight: 700;
    color: {green};
}}
QLabel#clock {{
    font-family: "DejaVu Sans Mono", monospace;
    font-weight: 700;
    color: {cyan};
}}

QTableView, QTreeView, QListView, QPlainTextEdit, QTextEdit {{
    background: {bg_alt};
    border: 1px solid {border};
    border-radius: 6px;
    gridline-color: {border};
    selection-background-color: {accent_dim};
    alternate-background-color: {bg};
}}
QHeaderView::section {{
    background: {panel};
    color: {text_dim};
    border: none;
    border-right: 1px solid {border};
    border-bottom: 1px solid {border};
    padding: 4px 6px;
}}
QTableView {{ font-family: "DejaVu Sans Mono", monospace; }}

QProgressBar {{
    border: 1px solid {border};
    border-radius: 6px;
    background: {bg_alt};
    text-align: center;
    height: 16px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0 y1:0 x2:1 y2:0,
        stop:0 {accent_dim}, stop:1 {accent});
    border-radius: 5px;
}}

QMenuBar {{ background: {bg_alt}; }}
QMenuBar::item:selected {{ background: {accent_dim}; }}
QMenu {{ background: {panel}; border: 1px solid {border}; }}
QMenu::item:selected {{ background: {accent_dim}; }}

QStatusBar {{ background: {bg_alt}; color: {text_dim}; }}
QStatusBar QLabel {{ color: {text_dim}; }}

QScrollBar:vertical {{ background: {bg}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 6px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {accent_dim}; }}
QScrollBar:horizontal {{ background: {bg}; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 6px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 6px; }}
QTabBar::tab {{
    background: {panel};
    padding: 7px 16px;
    border: 1px solid {border};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{ background: {panel_hi}; color: {accent}; }}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {border};
    border-radius: 4px;
    background: {bg_alt};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}
"""
