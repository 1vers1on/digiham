#!/usr/bin/env bash
# Wrap dist/digiham.app in a drag-to-Applications .dmg.
#
# Usage (on macOS, after `pyinstaller packaging/digiham.spec`):
#   packaging/macos/build-dmg.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
app="$root/dist/digiham.app"
out="$root/dist"

[ -d "$app" ] || { echo "error: $app not found — run PyInstaller first" >&2; exit 1; }

version="$(cd "$root" && python3 -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])' 2>/dev/null || echo 0.0.0)"
arch="$(uname -m)"                       # arm64 or x86_64
dmg="$out/digiham-${version}-macos-${arch}.dmg"

# Ad-hoc sign so the app at least runs after the Gatekeeper right-click-open
# (real Developer ID signing needs a paid cert the project doesn't ship with).
codesign --force --deep --sign - "$app" 2>/dev/null || \
  echo "note: ad-hoc codesign skipped/failed (non-fatal)"

staging="$(mktemp -d)/dmg"
mkdir -p "$staging"
cp -R "$app" "$staging/"
ln -s /Applications "$staging/Applications"

rm -f "$dmg"
echo "Building $dmg ..."
hdiutil create \
  -volname "digiham $version" \
  -srcfolder "$staging" \
  -ov -format UDZO \
  "$dmg"

echo "Built $dmg"
