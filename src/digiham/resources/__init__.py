"""Bundled, non-code resources (the app icon, etc.).

Resolving these through :func:`icon_path` keeps them working both from a normal
install (``importlib.resources``) and from a PyInstaller one-file build, where
the package is unpacked under ``sys._MEIPASS``.
"""

from __future__ import annotations

import sys
from importlib import resources
from pathlib import Path

ICON_NAME = "digiham.png"


def icon_path() -> str:
    """Absolute path to the app icon PNG, in dev and frozen builds alike."""
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks package data next to the code under _MEIPASS.
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = base / "digiham" / "resources" / ICON_NAME
        if candidate.exists():
            return str(candidate)

    with resources.as_file(resources.files(__name__) / ICON_NAME) as p:
        return str(p)
