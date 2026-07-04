"""WSJT-X-compatible ``ALL.TXT`` spot logging.

WSJT-X appends every decode (and every transmission) to a plain-text file
called ``ALL.TXT``. A surprising amount of the ecosystem — operators
grepping for a call, home-brew spotters, and some logging tools — reads
that file, so writing the same format makes digiham a drop-in for those
workflows.

Each line is::

    YYMMDD_HHMMSS   <dial MHz> <Rx|Tx> <mode> <snr> <dt> <audioHz> <message>

for example::

    260704_143000     14.074 Rx FT8   -10  0.2 1633 CQ DL1ABC JO31

The formatting mirrors WSJT-X closely enough for those consumers; it is a
log, not a protocol, so exact column widths are not load-bearing.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional


def format_line(when: dt.datetime, dial_mhz: float, is_tx: bool, mode: str,
                snr: float, delta_t: float, audio_hz: float,
                message: str) -> str:
    """Format one ALL.TXT line (without the trailing newline)."""
    ts = when.astimezone(dt.timezone.utc).strftime("%y%m%d_%H%M%S")
    rxtx = "Tx" if is_tx else "Rx"
    return (f"{ts}  {dial_mhz:9.3f} {rxtx} {mode:<4s} "
            f"{snr:+4.0f} {delta_t:+4.1f} {audio_hz:4.0f} {message}")


class SpotLog:
    """Append-only writer for an ``ALL.TXT`` style spot file."""

    def __init__(self, path: Path, enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled

    def _write(self, line: str) -> None:
        if not self.enabled:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def log_decode(self, when: dt.datetime, dial_mhz: float, mode: str,
                   snr: float, delta_t: float, audio_hz: float,
                   message: str) -> None:
        self._write(format_line(when, dial_mhz, False, mode, snr, delta_t,
                                audio_hz, message))

    def log_tx(self, when: dt.datetime, dial_mhz: float, mode: str,
               audio_hz: float, message: str) -> None:
        # Transmissions carry no SNR/DT of their own; WSJT-X logs zeros.
        self._write(format_line(when, dial_mhz, True, mode, 0.0, 0.0,
                                audio_hz, message))


def default_path(config_dir: Path, override: Optional[str] = None) -> Path:
    return Path(override) if override else Path(config_dir) / "ALL.TXT"
