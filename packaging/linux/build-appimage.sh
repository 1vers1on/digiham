#!/usr/bin/env bash
# Turn the PyInstaller one-folder build (dist/digiham) into a portable
# digiham-x86_64.AppImage. Download-and-run: no install, no root, no pip.
#
# Usage:  packaging/linux/build-appimage.sh
# Requires: a completed `pyinstaller packaging/digiham.spec` build in dist/,
#           plus curl (to fetch appimagetool) and FUSE or appimagetool's
#           --appimage-extract-and-run fallback.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
dist="$root/dist/digiham"
assets="$root/assets"
out="$root/dist"

[ -d "$dist" ] || { echo "error: $dist not found — run PyInstaller first" >&2; exit 1; }

version="$(cd "$root" && python3 -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])' 2>/dev/null || echo 0.0.0)"

appdir="$root/dist/AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr/bin" "$appdir/usr/share/applications" \
         "$appdir/usr/share/icons/hicolor/256x256/apps"

# App payload.
cp -a "$dist/." "$appdir/usr/bin/"

# Desktop entry + icon (required at both AppDir root and the hicolor path).
cp "$here/digiham.desktop" "$appdir/usr/share/applications/digiham.desktop"
cp "$here/digiham.desktop" "$appdir/digiham.desktop"
cp "$assets/digiham.png" "$appdir/usr/share/icons/hicolor/256x256/apps/digiham.png"
cp "$assets/digiham.png" "$appdir/digiham.png"
ln -sf usr/share/icons/hicolor/256x256/apps/digiham.png "$appdir/.DirIcon"

# AppRun -> the frozen launcher.
cat > "$appdir/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/digiham" "$@"
EOF
chmod +x "$appdir/AppRun"

# Match the AppImage arch to the machine we're building on (x86_64 or aarch64).
arch="$(uname -m)"
case "$arch" in
  x86_64|amd64)   arch="x86_64" ;;
  aarch64|arm64)  arch="aarch64" ;;
  *) echo "error: unsupported arch '$arch'" >&2; exit 1 ;;
esac

# Fetch the matching appimagetool if it isn't already on PATH / cached.
tool="$(command -v appimagetool || true)"
if [ -z "$tool" ]; then
  tool="$root/dist/appimagetool"
  if [ ! -x "$tool" ]; then
    echo "Downloading appimagetool ($arch) ..."
    curl -fsSL -o "$tool" \
      "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${arch}.AppImage"
    chmod +x "$tool"
  fi
fi

export ARCH="$arch"
target="$out/digiham-${version}-${arch}.AppImage"
echo "Building $target ..."
# --appimage-extract-and-run avoids needing FUSE inside CI containers.
"$tool" --appimage-extract-and-run "$appdir" "$target" \
  || APPIMAGE_EXTRACT_AND_RUN=1 "$tool" "$appdir" "$target"

echo "Built $target"
