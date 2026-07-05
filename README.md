<p align="center">
  <img src="assets/logo.svg" alt="digiham" width="128" height="128">
</p>

<h1 align="center">digiham</h1>

A modern, dark-mode **FT8 / FT4 / WSPR operating frontend** for amateur
radio — think WSJT-X, built on [`ft8lib`](https://pypi.org/project/ft8lib/),
Hamlib's `rigctld`, and Qt 6 (PySide6).

## Download & install

Grab the latest build for your OS from the
[**Releases**](https://github.com/1vers1on/digiham/releases) page — no Python,
no `pip`, nothing else to install.

| OS | File | How to install |
|----|------|----------------|
| **Windows** | `digiham-<version>-windows-setup.exe` | Run the installer, then launch **digiham** from the Start Menu. |
| **macOS** (Apple silicon) | `digiham-<version>-macos-arm64.dmg` | Open the DMG and drag **digiham** into **Applications**. First launch: right-click the app → **Open** (it's unsigned, so double-clicking is blocked once by Gatekeeper). |
| **Linux** (x86-64) | `digiham-<version>-x86_64.AppImage` | `chmod +x digiham-*.AppImage` then run it. Works on most modern distros; nothing to install. |
| **Linux** (ARM64 / aarch64) | `digiham-<version>-aarch64.AppImage` | Same as above — for Raspberry Pi (64-bit) and other ARM boards/SBCs. |

Every push also builds these as downloadable
[workflow artifacts](https://github.com/1vers1on/digiham/actions) if you want a
bleeding-edge build between releases.

> **Linux note:** Qt 6 needs `libxcb-cursor0` present on the host
> (`sudo apt install libxcb-cursor0` on Debian/Ubuntu). Everything else is
> bundled inside the AppImage.

## Features

- **Live decoding** of FT8, FT4 and WSPR from the sound card, aligned to
  the UTC T/R cycle, with an early decode each period so replies are ready
  before your transmit slot.
- **Auto-sequencing** of QSOs, exactly the WSJT-X exchange: double-click a
  CQ (or enable *Call 1st*) and digiham runs Tx1→Tx5, tracks the reports
  both ways, and closes the contact — no clicking required.
- **Automatic ADIF logging** on RR73/73, with duplicate suppression, a log
  viewer with worked-DXCC/grid/band tallies, and one-click ADIF export
  (LoTW / QRZ / Club Log compatible).
- **DXCC / country awareness**: every decode is tagged with the sending
  station's country and continent, unworked entities are flagged with a ★,
  and you can get an audible alert (and hide already-worked stations) — the
  award-chasing workflow WSJT-X users rely on, built in.
- **Tune button**: a steady carrier for tuning an ATU or setting amplifier
  drive, with the same split/PTT handling as a normal transmission.
- **ALL.TXT spot log** in WSJT-X's format, so operators and tools that grep
  or tail that file work unchanged.
- **Keyboard shortcuts** for the common actions: Esc halt, Ctrl+E enable Tx,
  Ctrl+T tune, Ctrl+R CQ, Ctrl+L log, Alt+↑/↓ nudge Rx.
- **Rig control via `rigctld`** on a background thread: QSY on band change,
  split operation, and PTT keying — nothing blocks the UI.
- **Spectrum + waterfall** with click-to-tune Rx/Tx cursors and selectable
  colour palettes.
- **Band Activity / Rx Frequency** panes with colour highlighting for CQ
  calls, new (unworked) stations, and messages addressed to you.
- **Six standard Tx messages** with *Now/Next* selection plus a free-text
  slot, Hold Tx Freq, Lock Tx=Rx, Tx even/odd, and a Tx watchdog.
- **WSJT-X UDP output** so companions like GridTracker and JTAlert can
  follow digiham as if it were WSJT-X (decodes, status, and logged QSOs).
- **Lots of settings**: station, radio, audio devices, decode depth &
  search window, behaviour toggles, and colours — all persisted to
  `~/.config/digiham/config.json`.

## Running from source (developers)

```bash
# from a virtualenv that has ft8lib installed
pip install -e .          # pulls in PySide6, sounddevice, scipy, numpy
digiham                    # launch the GUI
```

On first launch, open **File → Settings (F2)** and set your callsign and
grid before transmitting.

### Building the packages locally

The same one-folder build the CI uses:

```bash
pip install ".[packaging]"                     # adds PyInstaller
pyinstaller packaging/digiham.spec --noconfirm # -> dist/digiham (dist/digiham.app on macOS)

# then, per platform:
bash packaging/linux/build-appimage.sh                       # -> dist/*.AppImage
bash packaging/macos/build-dmg.sh                            # -> dist/*.dmg   (macOS)
iscc /DMyAppVersion=0.1.0 packaging\windows\digiham.iss      # -> dist/*setup.exe (Windows, Inno Setup)
```

The app icon lives in [`assets/logo.svg`](assets/logo.svg); regenerate the
`.png` / `.ico` / `.icns` derivatives with
[`assets/generate-icons.sh`](assets/generate-icons.sh) (needs Inkscape +
ImageMagick).

### Rig control

The release builds **bundle Hamlib** — digiham ships its own `rigctld`, so
rig control works out of the box with nothing else to install. In
Settings → Radio, tick **Enable rig control**, leave **Run a private rigctld
(built-in)** on, and pick your radio model and serial device: digiham starts
and supervises the bundled daemon for you.

digiham resolves `rigctld` in this order: the **bundled** copy first, then any
`rigctld` on your **PATH** (a system Hamlib), and finally the explicit path you
set in **rigctld binary** — which overrides both if you want a specific build.

If you'd rather run `rigctld` yourself (or point at one on another host),
untick **Run a private rigctld** and start it manually, e.g. an IC-7300:

```bash
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200
```

then set the host/port (default `localhost:4532`).

**Building the bundled Hamlib from source** (done automatically in CI; the
`Hamlib/` source tree is checked in):

```bash
bash packaging/build-hamlib.sh   # -> packaging/hamlib/bin/rigctld
```

The PyInstaller spec picks that up and ships it inside the app. Needs the
autotools toolchain (`autoconf automake libtool`) and libusb headers; on
Windows the build runs under MSYS2/MinGW and links statically.

### GridTracker / JTAlert (WSJT-X UDP)

In **Settings → Reporting**, tick **Broadcast WSJT-X UDP messages**.
digiham then emits the same UDP datagrams WSJT-X does — heartbeat, status,
decodes, and logged QSOs — so tools such as GridTracker or JTAlert can
follow it. Point them at the configured host/port (WSJT-X's default is
`127.0.0.1:2237`); use a multicast group address to feed several tools at
once.

## How it fits together

```
audio.Capture ─► engine.RadioEngine ─► decoder.DecodeController ─► ft8lib
   (ring buffer)      │  (UTC clock,        (worker thread)
                      │   scheduler)
rig.RigController ◄───┤
   (rigctld thread)   ├─► sequencer.Sequencer  (auto-seq state machine)
                      ├─► adif.QsoLog           (logging + export)
                      └─► gui.MainWindow        (Qt6 dark UI + waterfall)
```

Each module is UI-free and independently testable; `gui/` is a thin layer
of widgets over the engine's Qt-signal surface.

