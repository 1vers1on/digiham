# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for digiham (Windows / Linux / macOS).

Produces a one-folder build under ``dist/digiham`` (a ``digiham.app`` bundle on
macOS). The per-platform packaging steps in ``packaging/<os>/`` and the GitHub
Actions workflow turn that into an installer / AppImage / DMG.

    pyinstaller packaging/digiham.spec --noconfirm
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

ROOT = Path(SPECPATH).parent          # noqa: F821 (SPECPATH injected by PyInstaller)
ASSETS = ROOT / "assets"
SRC = ROOT / "src"

is_win = sys.platform.startswith("win")
is_mac = sys.platform == "darwin"

# Read the version straight from pyproject so it stays in one place.
try:
    import tomllib
    with (ROOT / "pyproject.toml").open("rb") as fh:
        VERSION = tomllib.load(fh)["project"]["version"]
except Exception:
    VERSION = "0.0.0"

# --- collect data/binaries for the compiled deps ---------------------------
datas = [(str(SRC / "digiham" / "resources" / "digiham.png"), "digiham/resources")]
binaries = []
hiddenimports = []

for pkg in ("ft8lib", "sounddevice", "scipy"):
    try:
        datas += collect_data_files(pkg)
        binaries += collect_dynamic_libs(pkg)
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

icon = None
if is_win:
    icon = str(ASSETS / "digiham.ico")
elif is_mac:
    icon = str(ASSETS / "digiham.icns")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "tkinter", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="digiham",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=is_mac,  # let macOS pass file/URL open events through
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="digiham",
)

if is_mac:
    app = BUNDLE(
        coll,
        name="digiham.app",
        icon=icon,
        bundle_identifier="com.ellierf.digiham",
        version=VERSION,
        info_plist={
            "CFBundleName": "digiham",
            "CFBundleDisplayName": "digiham",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # Sound-card capture needs an explicit purpose string on macOS.
            "NSMicrophoneUsageDescription":
                "digiham captures receiver audio from your sound card to "
                "decode FT8/FT4/WSPR signals.",
        },
    )
