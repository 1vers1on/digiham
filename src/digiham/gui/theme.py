"""Theming: a Fusion palette plus a hand-tuned, token-driven stylesheet.

The active colours live in the module-level :data:`PALETTE` dict, which the
decode tables and the waterfall import *by reference* and read at paint time.
Because of that, switching themes mutates ``PALETTE`` in place (never rebinds
it) so every importer picks up the new colours.

Themes are just a named set of colour tokens, all defined in
:data:`BUILTIN_THEMES`. A theme only has to spell out the tokens it wants to
change — anything it omits falls back to the default dark theme.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# The default dark theme's colour tokens. Also the fallback for any token a
# theme leaves out, so this dict defines the full set of valid keys.
DEFAULT_COLORS = {
    "bg":          "#14171c",
    "bg_alt":      "#181c22",
    "panel":       "#1e232b",
    "panel_hi":    "#252b34",
    "panel_hover": "#2c343f",
    "border":      "#2c333d",
    "text":        "#e6e9ef",
    "text_dim":    "#98a1b0",
    "accent":      "#4c8dff",
    "accent_dim":  "#2d5cad",
    "hl_text":     "#ffffff",   # text drawn on top of the accent highlight
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

DEFAULT_THEME = "Default Dark"

# Built-in themes. Each maps token -> colour; missing tokens inherit from
# DEFAULT_COLORS, so an alternate only needs to spell out what it changes.
# Light themes must also set hl_text (drawn on the accent highlight).
BUILTIN_THEMES: dict[str, dict[str, str]] = {
    DEFAULT_THEME: DEFAULT_COLORS,
    "Pastel Pink": {
        "bg": "#fff0f6", "bg_alt": "#ffe4ef", "panel": "#ffe0ec",
        "panel_hi": "#ffd2e1", "panel_hover": "#ffc4d8", "border": "#f3b8ce",
        "text": "#6b2d4f", "text_dim": "#a86b86", "accent": "#ff6fa5",
        "accent_dim": "#ff9ec2", "hl_text": "#ffffff", "green": "#3fa07a",
        "amber": "#d99a3f", "red": "#e0506a", "cyan": "#3fb0c0",
        "magenta": "#c264c9", "hl_cq": "#d9f0e3", "hl_tome": "#f0dcf2",
        "hl_newcall": "#dceaf5", "tx": "#f8d0d8",
    },
    "Nord": {
        "bg": "#2e3440", "bg_alt": "#292e39", "panel": "#3b4252",
        "panel_hi": "#434c5e", "panel_hover": "#464f62", "border": "#4c566a",
        "text": "#eceff4", "text_dim": "#a3adc2", "accent": "#88c0d0",
        "accent_dim": "#5e81ac", "green": "#a3be8c", "amber": "#ebcb8b",
        "red": "#bf616a", "cyan": "#8fbcbb", "magenta": "#b48ead",
        "hl_cq": "#3b4a3f", "hl_tome": "#43384a", "hl_newcall": "#34435a",
        "tx": "#4a2f33",
    },
    "Dracula": {
        "bg": "#282a36", "bg_alt": "#21222c", "panel": "#343746",
        "panel_hi": "#424450", "panel_hover": "#4a4d5e", "border": "#44475a",
        "text": "#f8f8f2", "text_dim": "#6272a4", "accent": "#bd93f9",
        "accent_dim": "#6f4fb0", "green": "#50fa7b", "amber": "#ffb86c",
        "red": "#ff5555", "cyan": "#8be9fd", "magenta": "#ff79c6",
        "hl_cq": "#253d33", "hl_tome": "#3a2a45", "hl_newcall": "#2a3550",
        "tx": "#4a2a2a",
    },
    "Tokyo Night": {
        "bg": "#1a1b26", "bg_alt": "#16161e", "panel": "#24283b",
        "panel_hi": "#2f3549", "panel_hover": "#363b54", "border": "#414868",
        "text": "#c0caf5", "text_dim": "#565f89", "accent": "#7aa2f7",
        "accent_dim": "#3d59a1", "green": "#9ece6a", "amber": "#e0af68",
        "red": "#f7768e", "cyan": "#7dcfff", "magenta": "#bb9af7",
        "hl_cq": "#21382e", "hl_tome": "#33294a", "hl_newcall": "#24304d",
        "tx": "#452830",
    },
    "Catppuccin Mocha": {
        "bg": "#1e1e2e", "bg_alt": "#181825", "panel": "#313244",
        "panel_hi": "#45475a", "panel_hover": "#494d64", "border": "#45475a",
        "text": "#cdd6f4", "text_dim": "#7f849c", "accent": "#89b4fa",
        "accent_dim": "#4a6bb3", "green": "#a6e3a1", "amber": "#f9e2af",
        "red": "#f38ba8", "cyan": "#94e2d5", "magenta": "#cba6f7",
        "hl_cq": "#26402f", "hl_tome": "#382c48", "hl_newcall": "#28344f",
        "tx": "#472a34",
    },
    "Catppuccin Latte": {
        "bg": "#eff1f5", "bg_alt": "#e6e9ef", "panel": "#dce0e8",
        "panel_hi": "#ccd0da", "panel_hover": "#bcc0cc", "border": "#acb0be",
        "text": "#4c4f69", "text_dim": "#6c6f85", "accent": "#1e66f5",
        "accent_dim": "#7aa0f0", "hl_text": "#ffffff", "green": "#40a02b",
        "amber": "#df8e1d", "red": "#d20f39", "cyan": "#179299",
        "magenta": "#8839ef", "hl_cq": "#d5ead2", "hl_tome": "#e8dcf3",
        "hl_newcall": "#d5e0f5", "tx": "#f2d5da",
    },
    "Gruvbox Dark": {
        "bg": "#282828", "bg_alt": "#1d2021", "panel": "#3c3836",
        "panel_hi": "#504945", "panel_hover": "#453f3b", "border": "#665c54",
        "text": "#ebdbb2", "text_dim": "#a89984", "accent": "#83a598",
        "accent_dim": "#458588", "green": "#b8bb26", "amber": "#fabd2f",
        "red": "#fb4934", "cyan": "#8ec07c", "magenta": "#d3869b",
        "hl_cq": "#34412c", "hl_tome": "#402c3a", "hl_newcall": "#2c3a44",
        "tx": "#4a2a26",
    },
    "Gruvbox Light": {
        "bg": "#fbf1c7", "bg_alt": "#f2e5bc", "panel": "#ebdbb2",
        "panel_hi": "#d5c4a1", "panel_hover": "#ccba98", "border": "#bdae93",
        "text": "#3c3836", "text_dim": "#7c6f64", "accent": "#076678",
        "accent_dim": "#83a598", "hl_text": "#ffffff", "green": "#79740e",
        "amber": "#b57614", "red": "#9d0006", "cyan": "#427b58",
        "magenta": "#8f3f71", "hl_cq": "#dbe4bc", "hl_tome": "#e8d8db",
        "hl_newcall": "#d0dcd0", "tx": "#eccfc4",
    },
    "One Dark": {
        "bg": "#282c34", "bg_alt": "#21252b", "panel": "#2c313a",
        "panel_hi": "#3a3f4b", "panel_hover": "#3e4451", "border": "#3e4451",
        "text": "#abb2bf", "text_dim": "#5c6370", "accent": "#61afef",
        "accent_dim": "#3b6ea5", "green": "#98c379", "amber": "#e5c07b",
        "red": "#e06c75", "cyan": "#56b6c2", "magenta": "#c678dd",
        "hl_cq": "#26382c", "hl_tome": "#35293f", "hl_newcall": "#263548",
        "tx": "#43282c",
    },
    "Monokai": {
        "bg": "#272822", "bg_alt": "#1e1f1c", "panel": "#35362f",
        "panel_hi": "#414339", "panel_hover": "#494b40", "border": "#49483e",
        "text": "#f8f8f2", "text_dim": "#75715e", "accent": "#66d9ef",
        "accent_dim": "#3a7d88", "green": "#a6e22e", "amber": "#fd971f",
        "red": "#f92672", "cyan": "#66d9ef", "magenta": "#ae81ff",
        "hl_cq": "#303a20", "hl_tome": "#35304a", "hl_newcall": "#26343f",
        "tx": "#45252f",
    },
    "Solarized Dark": {
        "bg": "#002b36", "bg_alt": "#073642", "panel": "#073642",
        "panel_hi": "#0a4653", "panel_hover": "#0d515f", "border": "#144a54",
        "text": "#839496", "text_dim": "#586e75", "accent": "#268bd2",
        "accent_dim": "#1a5a86", "green": "#859900", "amber": "#b58900",
        "red": "#dc322f", "cyan": "#2aa198", "magenta": "#6c71c4",
        "hl_cq": "#0a4034", "hl_tome": "#243a4a", "hl_newcall": "#0d3d55",
        "tx": "#3f2a2a",
    },
    "Solarized Light": {
        "bg": "#fdf6e3", "bg_alt": "#eee8d5", "panel": "#eee8d5",
        "panel_hi": "#e3ddc8", "panel_hover": "#e3ddc8", "border": "#d5cdb3",
        "text": "#073642", "text_dim": "#657b83", "accent": "#268bd2",
        "accent_dim": "#93c4e8", "hl_text": "#ffffff", "green": "#859900",
        "amber": "#b58900", "red": "#dc322f", "cyan": "#2aa198",
        "magenta": "#6c71c4", "hl_cq": "#d9e6c8", "hl_tome": "#e6d9ec",
        "hl_newcall": "#d4e4f2", "tx": "#f2d0cf",
    },
    "Rosé Pine": {
        "bg": "#191724", "bg_alt": "#1f1d2e", "panel": "#26233a",
        "panel_hi": "#2a2740", "panel_hover": "#302d47", "border": "#403d52",
        "text": "#e0def4", "text_dim": "#6e6a86", "accent": "#c4a7e7",
        "accent_dim": "#6c5a8c", "green": "#56949f", "amber": "#f6c177",
        "red": "#eb6f92", "cyan": "#9ccfd8", "magenta": "#c4a7e7",
        "hl_cq": "#1f3a34", "hl_tome": "#2f2740", "hl_newcall": "#24314a",
        "tx": "#3f2530",
    },
    "Everforest Dark": {
        "bg": "#2d353b", "bg_alt": "#272e33", "panel": "#374247",
        "panel_hi": "#414b50", "panel_hover": "#4a555b", "border": "#4f585e",
        "text": "#d3c6aa", "text_dim": "#859289", "accent": "#7fbbb3",
        "accent_dim": "#4d7a74", "green": "#a7c080", "amber": "#dbbc7f",
        "red": "#e67e80", "cyan": "#83c092", "magenta": "#d699b6",
        "hl_cq": "#34402c", "hl_tome": "#3f333f", "hl_newcall": "#2f3a44",
        "tx": "#46302f",
    },
    "Ayu Dark": {
        "bg": "#0b0e14", "bg_alt": "#0d1017", "panel": "#131721",
        "panel_hi": "#1c212b", "panel_hover": "#232834", "border": "#1f2430",
        "text": "#bfbdb6", "text_dim": "#565b66", "accent": "#39bae6",
        "accent_dim": "#2a7ea3", "green": "#aad94c", "amber": "#ffb454",
        "red": "#f26d78", "cyan": "#73b8ff", "magenta": "#d2a6ff",
        "hl_cq": "#16351f", "hl_tome": "#2a2440", "hl_newcall": "#12304a",
        "tx": "#3f2530",
    },
    "Ayu Light": {
        "bg": "#fcfcfc", "bg_alt": "#f3f4f5", "panel": "#ececec",
        "panel_hi": "#e0e1e2", "panel_hover": "#d5d6d8", "border": "#d9d9d9",
        "text": "#5c6166", "text_dim": "#8a9199", "accent": "#399ee6",
        "accent_dim": "#8cc6ef", "hl_text": "#ffffff", "green": "#86b300",
        "amber": "#f2ae49", "red": "#e65050", "cyan": "#55b4d4",
        "magenta": "#a37acc", "hl_cq": "#dceac2", "hl_tome": "#ebdcf2",
        "hl_newcall": "#d2e6f5", "tx": "#f5d5d5",
    },
    "GitHub Light": {
        "bg": "#ffffff", "bg_alt": "#f6f8fa", "panel": "#f6f8fa",
        "panel_hi": "#eaeef2", "panel_hover": "#dfe3e8", "border": "#d0d7de",
        "text": "#1f2328", "text_dim": "#656d76", "accent": "#0969da",
        "accent_dim": "#8cb6e8", "hl_text": "#ffffff", "green": "#1a7f37",
        "amber": "#9a6700", "red": "#cf222e", "cyan": "#1b7c83",
        "magenta": "#8250df", "hl_cq": "#d4ecdd", "hl_tome": "#ece2f7",
        "hl_newcall": "#ddeafd", "tx": "#f7d9dc",
    },
    "Material Ocean": {
        "bg": "#0f111a", "bg_alt": "#090b10", "panel": "#1a1c25",
        "panel_hi": "#232530", "panel_hover": "#2a2d3a", "border": "#2a2d3a",
        "text": "#a6accd", "text_dim": "#4b526d", "accent": "#82aaff",
        "accent_dim": "#3d5a99", "green": "#c3e88d", "amber": "#ffcb6b",
        "red": "#f07178", "cyan": "#89ddff", "magenta": "#c792ea",
        "hl_cq": "#2a3a2c", "hl_tome": "#33294a", "hl_newcall": "#24314d",
        "tx": "#45282f",
    },
    "Synthwave": {
        "bg": "#1a1626", "bg_alt": "#14101f", "panel": "#241b38",
        "panel_hi": "#2f2347", "panel_hover": "#382a54", "border": "#3d2e5c",
        "text": "#f0e6ff", "text_dim": "#8b7aad", "accent": "#ff2e97",
        "accent_dim": "#a01e63", "green": "#2de2a3", "amber": "#ffcc4d",
        "red": "#ff4d6d", "cyan": "#2de6ff", "magenta": "#d16aff",
        "hl_cq": "#14382f", "hl_tome": "#3a2247", "hl_newcall": "#1f2f52",
        "tx": "#4a1f33",
    },
}

# The live palette. Imported by reference elsewhere, so only ever mutated in
# place (see _set_palette) — never rebound.
PALETTE: dict[str, str] = dict(DEFAULT_COLORS)


def available_themes() -> dict[str, dict[str, str]]:
    """All themes by name."""
    return dict(BUILTIN_THEMES)


def resolve_colors(theme: str | None) -> dict[str, str]:
    """Full token set for ``theme``, filling any gaps from the default theme."""
    chosen = BUILTIN_THEMES.get(theme or DEFAULT_THEME, {})
    merged = dict(DEFAULT_COLORS)
    merged.update(chosen)
    return merged


def _set_palette(colors: dict[str, str]) -> None:
    PALETTE.clear()
    PALETTE.update(colors)


def _c(key: str) -> QColor:
    return QColor(PALETTE[key])


def apply_theme(app: QApplication, font_size: int = 11,
                theme: str | None = None) -> None:
    """Load ``theme`` into the live palette and apply it to ``app``."""
    _set_palette(resolve_colors(theme))

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
    pal.setColor(QPalette.ColorRole.HighlightedText, _c("hl_text"))
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
QPushButton:hover {{ background: {panel_hover}; border-color: {accent_dim}; }}
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
