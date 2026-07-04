"""Example plugin: contribute custom colour themes to digiham.

Return themes from ``provide_themes`` (declarative) and/or call
``self.ctx.register_theme(name, colors)`` at runtime. Either way the themes
appear in Settings → Colours → Theme, and are removed again when the
plugin is unloaded or reloaded.

A theme only has to name the tokens it wants to change; anything it leaves
out inherits the default dark theme. The available tokens are the keys of
``digiham.gui.theme.DEFAULT_COLORS`` (bg, panel, text, accent, green, red,
hl_cq, …).
"""

from digiham.plugins import Plugin


class SolarTheme(Plugin):
    name = "solar-theme"
    version = "1.0"
    author = "digiham examples"
    description = "Adds 'Solar Flare' and 'Deep Space' colour themes"

    def provide_themes(self):
        return {
            "Solar Flare": {
                "bg": "#1a0f07", "bg_alt": "#150b05", "panel": "#2a1810",
                "panel_hi": "#3a2216", "panel_hover": "#472a1b",
                "border": "#5c3620", "text": "#ffe8d6", "text_dim": "#c69672",
                "accent": "#ff8c42", "accent_dim": "#b5591f",
                "green": "#7fb069", "amber": "#ffcb47", "red": "#ff5a4d",
                "cyan": "#4bc6b9", "magenta": "#e07be0",
                "hl_cq": "#2e3a1e", "hl_tome": "#3d2438",
                "hl_newcall": "#3a2a1a", "tx": "#5a2418",
            },
            "Deep Space": {
                "bg": "#05060f", "bg_alt": "#03040a", "panel": "#0c0f1e",
                "panel_hi": "#141830", "panel_hover": "#1b2040",
                "border": "#232a4d", "text": "#d6e0ff", "text_dim": "#6b76a8",
                "accent": "#6c8cff", "accent_dim": "#3a4d99",
                "green": "#4ad6a0", "amber": "#ffc861", "red": "#ff6b8a",
                "cyan": "#5fd0e6", "magenta": "#b088ff",
                "hl_cq": "#14352c", "hl_tome": "#2a2450",
                "hl_newcall": "#1a2a55", "tx": "#3f1f33",
            },
        }

    def on_load(self):
        self.ctx.status("solar-theme: added Solar Flare + Deep Space themes")
