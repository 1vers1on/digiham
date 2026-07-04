#!/usr/bin/env bash
# Regenerate every icon asset from the master logo.svg.
#
# Requires: inkscape (SVG -> PNG) and ImageMagick (`magick`) for .ico/.icns.
# Run from anywhere:  ./assets/generate-icons.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
svg="$here/logo.svg"
png_dir="$here/png"
mkdir -p "$png_dir"

render() { inkscape "$svg" -w "$1" -h "$1" -o "$2" >/dev/null 2>&1; }

echo "Rendering PNGs from logo.svg ..."
for size in 16 32 48 64 128 256 512 1024; do
  render "$size" "$png_dir/digiham-${size}.png"
done

# Canonical PNG used on Linux (.desktop / AppImage) and as the Qt window icon.
cp "$png_dir/digiham-256.png" "$here/digiham.png"

echo "Building Windows icon (digiham.ico) ..."
magick "$png_dir/digiham-16.png" "$png_dir/digiham-32.png" \
       "$png_dir/digiham-48.png" "$png_dir/digiham-64.png" \
       "$png_dir/digiham-128.png" "$png_dir/digiham-256.png" \
       "$here/digiham.ico"

echo "Building macOS icon (digiham.icns) ..."
if command -v iconutil >/dev/null 2>&1; then
  # The proper, Apple-native path (available on macOS / CI runners).
  iconset="$(mktemp -d)/digiham.iconset"
  mkdir -p "$iconset"
  render 16   "$iconset/icon_16x16.png"
  render 32   "$iconset/icon_16x16@2x.png"
  render 32   "$iconset/icon_32x32.png"
  render 64   "$iconset/icon_32x32@2x.png"
  render 128  "$iconset/icon_128x128.png"
  render 256  "$iconset/icon_128x128@2x.png"
  render 256  "$iconset/icon_256x256.png"
  render 512  "$iconset/icon_256x256@2x.png"
  render 512  "$iconset/icon_512x512.png"
  render 1024 "$iconset/icon_512x512@2x.png"
  iconutil -c icns "$iconset" -o "$here/digiham.icns"
else
  # Fallback for non-macOS dev machines: a valid single-resolution icns.
  # CI regenerates a full multi-resolution icns with iconutil on macOS.
  magick "$png_dir/digiham-512.png" "$here/digiham.icns"
fi

echo "Done. Assets written to $here"
