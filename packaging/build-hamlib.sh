#!/usr/bin/env bash
# Build Hamlib from the bundled ``Hamlib/`` source tree and stage the parts
# digiham ships: the ``rigctld`` daemon and whatever shared libraries it needs
# to run.
#
# The result lands in ``packaging/hamlib/`` (git-ignored):
#
#     packaging/hamlib/bin/rigctld[.exe]
#     packaging/hamlib/lib/*            (only the dynamic libs, if any)
#
# The PyInstaller spec (packaging/digiham.spec) picks that up and drops it under
# ``hamlib/`` inside the frozen app, and rigctl.find_rigctld() looks there first
# at runtime.
#
# Works on Linux, macOS, and Windows (under an MSYS2 / MinGW bash). Hamlib is
# linked *statically* so rigctld is a single self-contained binary with no
# libhamlib to chase at load time; only third-party deps (libusb, …) may remain
# dynamic, and we stage those DLLs explicitly on Windows.
#
# Usage:  packaging/build-hamlib.sh [--clean]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
src="$root/Hamlib"
stage="$root/packaging/hamlib"
install="$root/packaging/.hamlib-install"

[ -d "$src" ] || { echo "error: Hamlib source not found at $src" >&2; exit 1; }

exe_suffix=""
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) exe_suffix=".exe" ;;
esac

if [ "${1:-}" = "--clean" ]; then
  echo "Cleaning previous Hamlib build ..."
  ( cd "$src" && make distclean >/dev/null 2>&1 || true )
  rm -rf "$stage" "$install"
fi

# If we already have a staged rigctld, don't rebuild (CI caches Hamlib/ and this
# keeps repeat builds fast). Force a rebuild with --clean.
if [ -x "$stage/bin/rigctld$exe_suffix" ]; then
  echo "Hamlib already staged at $stage — skipping build (use --clean to force)"
  exit 0
fi

njobs="$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2) )"

# 1. Generate ./configure the first time (needs autoconf/automake/libtool).
if [ ! -x "$src/configure" ]; then
  echo "Bootstrapping Hamlib (autoreconf) ..."
  ( cd "$src" && ./bootstrap )
fi

# 2. Configure: static libhamlib, no language bindings, all radio backends.
#    A static libhamlib means rigctld carries the whole backend catalogue
#    with no libhamlib.so/.dylib/.dll to locate at runtime.
if [ ! -f "$src/Makefile" ]; then
  echo "Configuring Hamlib ..."
  cflags="-O2 -fPIC"
  ldflags=""
  case "$(uname -s)" in
    Darwin) macos_min="${MACOSX_DEPLOYMENT_TARGET:-11.0}"
            cflags="$cflags -mmacosx-version-min=$macos_min" ;;
    MINGW*|MSYS*|CYGWIN*)
            # Link the whole thing statically on Windows so rigctld.exe carries
            # no MinGW runtime or libusb DLLs — one file to ship, no PATH games.
            ldflags="-static" ;;
  esac
  # --without-indi/readline drop libindiclient, libnova, libreadline and
  # libncurses (INDI is telescope control; readline is only rigctl's
  # interactive prompt, which the daemon never uses). libusb stays — plenty
  # of radios present a USB CAT interface.
  ( cd "$src" && ./configure \
      --prefix="$install" \
      --enable-static --disable-shared \
      --without-cxx-binding \
      --without-indi \
      --without-readline \
      --disable-dependency-tracking \
      CFLAGS="$cflags" LDFLAGS="$ldflags" )
fi

# 3. Build and install into a throwaway prefix.
echo "Building Hamlib (make -j$njobs) ..."
( cd "$src" && make -j"$njobs" )
( cd "$src" && make install )

# 4. Stage exactly what we ship.
echo "Staging rigctld into $stage ..."
rm -rf "$stage"
mkdir -p "$stage/bin" "$stage/lib"
cp "$install/bin/rigctld$exe_suffix" "$stage/bin/"
chmod +x "$stage/bin/rigctld$exe_suffix"

# With a static build there is usually no libhamlib to copy, but if a shared
# build slipped through (or a platform forced one), carry the libs along so the
# daemon can still load them from beside itself.
shopt -s nullglob
libs=( "$install"/lib/libhamlib*.so* "$install"/lib/libhamlib*.dylib "$install"/bin/libhamlib*.dll )
if [ "${#libs[@]}" -gt 0 ]; then
  cp "${libs[@]}" "$stage/lib/"
  echo "Staged shared libs: ${libs[*]##*/}"
fi
shopt -u nullglob

# On Windows, a mostly-static rigctld can still depend on a few MinGW DLLs
# (notably libusb-1.0.dll). Put those beside rigctld.exe so it runs on hosts
# without an MSYS2/MinGW installation.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    if command -v ldd >/dev/null 2>&1; then
      mapfile -t dlls < <(
        ldd "$stage/bin/rigctld$exe_suffix" 2>/dev/null \
          | sed -nE 's/.*=>[[:space:]]+(\/[^[:space:]]+\.dll).*/\1/p' \
          | grep -E '^/(mingw64|ucrt64|clang64|clangarm64)/bin/' \
          | sort -u
      )
      if [ "${#dlls[@]}" -gt 0 ]; then
        cp "${dlls[@]}" "$stage/bin/"
        echo "Staged runtime DLLs: ${dlls[*]##*/}"
      fi
    fi
    ;;
esac

echo "Done. rigctld -> $stage/bin/rigctld$exe_suffix"
"$stage/bin/rigctld$exe_suffix" --version || true
