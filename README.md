# digiham

A modern, dark-mode **FT8 / FT4 / WSPR operating frontend** for amateur
radio — think WSJT-X, built on [`ft8lib`](https://pypi.org/project/ft8lib/),
Hamlib's `rigctld`, and Qt 6 (PySide6).

## Features

- **Live decoding** of FT8, FT4 and WSPR from the sound card, aligned to
  the UTC T/R cycle, with an early decode each period so replies are ready
  before your transmit slot.
- **Auto-sequencing** of QSOs, exactly the WSJT-X exchange: double-click a
  CQ (or enable *Call 1st*) and digiham runs Tx1→Tx5, tracks the reports
  both ways, and closes the contact — no clicking required.
- **Automatic ADIF logging** on RR73/73, with duplicate suppression, a log
  viewer, and one-click ADIF export (LoTW / QRZ / Club Log compatible).
- **Rig control via `rigctld`** on a background thread: QSY on band change,
  split operation, and PTT keying — nothing blocks the UI.
- **Spectrum + waterfall** with click-to-tune Rx/Tx cursors and selectable
  colour palettes.
- **Band Activity / Rx Frequency** panes with colour highlighting for CQ
  calls, new (unworked) stations, and messages addressed to you.
- **Six standard Tx messages** with *Now/Next* selection plus a free-text
  slot, Hold Tx Freq, Lock Tx=Rx, Tx even/odd, and a Tx watchdog.
- **Lots of settings**: station, radio, audio devices, decode depth &
  search window, behaviour toggles, and colours — all persisted to
  `~/.config/digiham/config.json`.

## Running

```bash
# from a virtualenv that has ft8lib installed
pip install -e .          # pulls in PySide6, sounddevice, scipy, numpy
digiham                    # launch the GUI
```

On first launch, open **File → Settings (F2)** and set your callsign and
grid before transmitting.

### Rig control

Start `rigctld` for your radio, e.g. an IC-7300:

```bash
rigctld -m 3073 -r /dev/ttyUSB0 -s 115200
```

Then tick **Enable rig control** in Settings → Radio (default
`localhost:4532`).

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

## License

MIT
