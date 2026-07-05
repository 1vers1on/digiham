"""ADIF logging: an in-memory QSO log that appends to an ``.adi`` file.

ADIF (Amateur Data Interchange Format) records are a flat sequence of
``<FIELD:len>value`` tokens terminated by ``<EOR>``. We write a small,
widely-compatible subset understood by LoTW, QRZ, eQSL and Club Log.
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

APP_NAME = "digiham"
APP_VERSION = "1.0.1"


@dataclass(frozen=True)
class ImportResult:
    """Outcome of importing an ADIF file into the log."""
    added: int = 0
    duplicates: int = 0

    @property
    def read(self) -> int:
        return self.added + self.duplicates

    def summary(self) -> str:
        msg = f"imported {self.added} new QSO" + ("s" if self.added != 1 else "")
        if self.duplicates:
            msg += f" ({self.duplicates} duplicate" \
                   f"{'s' if self.duplicates != 1 else ''} skipped)"
        return msg


@dataclass
class Qso:
    call: str
    qso_date: str            # YYYYMMDD (UTC)
    time_on: str             # HHMMSS (UTC)
    band: str                # e.g. "20m"
    mode: str                # FT8/FT4/WSPR (ADIF submode handled below)
    freq_mhz: float          # RF frequency in MHz
    rst_sent: str = ""
    rst_rcvd: str = ""
    gridsquare: str = ""
    station_callsign: str = ""
    my_gridsquare: str = ""
    tx_pwr_w: Optional[float] = None
    qso_date_off: str = ""
    time_off: str = ""
    comment: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple:
        return (self.call.upper(), self.qso_date, self.time_on, self.band)


def _adif_field(name: str, value: str) -> str:
    value = str(value)
    return f"<{name}:{len(value.encode('utf-8'))}>{value}"


# Column order for CSV export.
_CSV_COLS = [
    "call", "qso_date", "time_on", "time_off", "band", "mode", "freq_mhz",
    "rst_sent", "rst_rcvd", "gridsquare", "station_callsign", "my_gridsquare",
    "tx_pwr_w", "comment",
]


# WSJT-X-style modes map to ADIF MODE plus SUBMODE.
_ADIF_MODE = {
    "FT8": ("FT8", ""),
    "FT4": ("MFSK", "FT4"),
    "WSPR": ("WSPR", ""),
}


def qso_to_adif(q: Qso) -> str:
    mode, submode = _ADIF_MODE.get(q.mode.upper(), (q.mode.upper(), ""))
    parts = [
        _adif_field("CALL", q.call.upper()),
        _adif_field("QSO_DATE", q.qso_date),
        _adif_field("TIME_ON", q.time_on),
        _adif_field("BAND", q.band),
        _adif_field("MODE", mode),
        _adif_field("FREQ", f"{q.freq_mhz:.6f}".rstrip("0").rstrip(".")),
    ]
    if submode:
        parts.append(_adif_field("SUBMODE", submode))
    if q.qso_date_off:
        parts.append(_adif_field("QSO_DATE_OFF", q.qso_date_off))
    if q.time_off:
        parts.append(_adif_field("TIME_OFF", q.time_off))
    if q.rst_sent:
        parts.append(_adif_field("RST_SENT", q.rst_sent))
    if q.rst_rcvd:
        parts.append(_adif_field("RST_RCVD", q.rst_rcvd))
    if q.gridsquare:
        parts.append(_adif_field("GRIDSQUARE", q.gridsquare))
    if q.station_callsign:
        parts.append(_adif_field("STATION_CALLSIGN", q.station_callsign.upper()))
    if q.my_gridsquare:
        parts.append(_adif_field("MY_GRIDSQUARE", q.my_gridsquare))
    if q.tx_pwr_w is not None:
        parts.append(_adif_field("TX_PWR", f"{q.tx_pwr_w:g}"))
    if q.comment:
        parts.append(_adif_field("COMMENT", q.comment))
    for k, v in q.extra.items():
        parts.append(_adif_field(k.upper(), v))
    parts.append("<EOR>")
    return " ".join(parts)


def adif_header() -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d %H%M%S")
    return (
        f"digiham ADIF export\n"
        f"<ADIF_VER:5>3.1.4\n"
        f"<PROGRAMID:{len(APP_NAME)}>{APP_NAME}\n"
        f"<PROGRAMVERSION:{len(APP_VERSION)}>{APP_VERSION}\n"
        f"<CREATED_TIMESTAMP:15>{now}\n"
        f"<EOH>\n"
    )


class QsoLog:
    """In-memory list of QSOs, backed by an append-only ADIF file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.records: list[Qso] = []
        self._keys: set[tuple] = set()
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        try:
            text = self.path.read_text(errors="replace")
        except OSError:
            return
        for q in parse_adif(text):
            if q.key not in self._keys:
                self.records.append(q)
                self._keys.add(q.key)

    def _ensure_header(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w") as f:
                f.write(adif_header())

    def add(self, q: Qso) -> bool:
        """Append a QSO; returns False if it's a duplicate of a logged key.

        The record is committed to memory only after it is safely written to
        disk, so a failed write (full disk, permissions, unplugged drive)
        raises OSError without leaving the in-memory log out of sync.
        """
        if q.key in self._keys:
            return False
        self._ensure_header()
        with self.path.open("a") as f:
            f.write(qso_to_adif(q) + "\n")
        self.records.append(q)
        self._keys.add(q.key)
        return True

    def import_adif(self, path: Path) -> ImportResult:
        """Merge QSOs from an external ADIF file into the log.

        Records already present (by call/date/time/band key) are skipped, as
        are duplicates within the imported file itself. New records are
        appended to the log file; nothing is committed to memory until the
        write succeeds. Raises OSError if the source or log file can't be read
        or written.
        """
        text = Path(path).read_text(errors="replace")
        new: list[Qso] = []
        seen_local: set[tuple] = set()
        duplicates = 0
        for q in parse_adif(text):
            if not q.call:
                continue
            k = q.key
            if k in self._keys or k in seen_local:
                duplicates += 1
                continue
            seen_local.add(k)
            new.append(q)
        if new:
            self._ensure_header()
            with self.path.open("a") as f:
                for q in new:
                    f.write(qso_to_adif(q) + "\n")
            for q in new:
                self.records.append(q)
                self._keys.add(q.key)
        logger.info("imported %d QSOs (%d duplicates) from %s",
                    len(new), duplicates, path)
        return ImportResult(added=len(new), duplicates=duplicates)

    def worked_calls(self) -> set[str]:
        return {r.call.upper() for r in self.records}

    def worked_on(self, band: str, mode: str) -> set[str]:
        return {
            r.call.upper() for r in self.records
            if r.band == band and r.mode.upper() == mode.upper()
        }

    def worked_grids(self) -> set[str]:
        """Set of 4-character grid squares already in the log."""
        return {r.gridsquare.upper()[:4] for r in self.records
                if len(r.gridsquare) >= 4}

    def worked_dxcc(self) -> set[str]:
        """Set of DXCC entity names already worked (resolved from calls)."""
        from . import dxcc
        out: set[str] = set()
        for r in self.records:
            name = dxcc.country(r.call)
            if name:
                out.add(name)
        return out

    def stats(self) -> dict:
        """Quick award-chasing tallies over the whole log."""
        from . import dxcc
        bands: set[str] = set()
        modes: set[str] = set()
        for r in self.records:
            if r.band:
                bands.add(r.band)
            if r.mode:
                modes.add(r.mode.upper())
        return {
            "qsos": len(self.records),
            "calls": len(self.worked_calls()),
            "dxcc": len(self.worked_dxcc()),
            "grids": len(self.worked_grids()),
            "bands": len(bands),
            "modes": len(modes),
        }

    def export(self, path: Path, records: Optional[Iterable[Qso]] = None) -> int:
        recs = list(records) if records is not None else self.records
        path = Path(path)
        with path.open("w") as f:
            f.write(adif_header())
            for q in recs:
                f.write(qso_to_adif(q) + "\n")
        return len(recs)

    def export_csv(self, path: Path, records: Optional[Iterable[Qso]] = None) -> int:
        """Write the log as a spreadsheet-friendly CSV file."""
        recs = list(records) if records is not None else self.records
        with Path(path).open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([c.upper() for c in _CSV_COLS])
            for q in recs:
                w.writerow([
                    q.call.upper(), q.qso_date, q.time_on, q.time_off,
                    q.band, q.mode,
                    f"{q.freq_mhz:.6f}".rstrip("0").rstrip("."),
                    q.rst_sent, q.rst_rcvd, q.gridsquare,
                    q.station_callsign.upper(), q.my_gridsquare,
                    "" if q.tx_pwr_w is None else f"{q.tx_pwr_w:g}",
                    q.comment,
                ])
        return len(recs)


# --- minimal ADIF reader (for reloading our own log) --------------------

def parse_adif(text: str) -> list[Qso]:
    # Skip an optional header up to <EOH>.
    low = text.lower()
    idx = low.find("<eoh>")
    if idx != -1:
        text = text[idx + 5:]
    records: list[Qso] = []
    for chunk in _split_records(text):
        fields = _parse_fields(chunk)
        if not fields.get("call"):
            continue
        records.append(_qso_from_fields(fields))
    return records


def _split_records(text: str) -> Iterable[str]:
    low = text.lower()
    start = 0
    while True:
        end = low.find("<eor>", start)
        if end == -1:
            break
        yield text[start:end]
        start = end + 5


def _parse_fields(chunk: str) -> dict:
    fields: dict[str, str] = {}
    i = 0
    n = len(chunk)
    while i < n:
        lt = chunk.find("<", i)
        if lt == -1:
            break
        gt = chunk.find(">", lt)
        if gt == -1:
            break
        spec = chunk[lt + 1:gt]
        i = gt + 1
        bits = spec.split(":")
        name = bits[0].strip().lower()
        if len(bits) < 2:
            continue
        try:
            length = int(bits[1])
        except ValueError:
            continue
        value = chunk[i:i + length]
        i += length
        fields[name] = value
    return fields


def _qso_from_fields(f: dict) -> Qso:
    known = {
        "call", "qso_date", "time_on", "band", "mode", "submode", "freq",
        "rst_sent", "rst_rcvd", "gridsquare", "station_callsign",
        "my_gridsquare", "tx_pwr", "qso_date_off", "time_off", "comment",
    }
    mode = f.get("mode", "").upper()
    submode = f.get("submode", "").upper()
    if submode == "FT4":
        mode = "FT4"
    try:
        freq = float(f.get("freq", "0") or 0)
    except ValueError:
        freq = 0.0
    try:
        pwr = float(f["tx_pwr"]) if f.get("tx_pwr") else None
    except ValueError:
        pwr = None
    extra = {k.upper(): v for k, v in f.items() if k not in known}
    return Qso(
        call=f.get("call", ""),
        qso_date=f.get("qso_date", ""),
        time_on=f.get("time_on", ""),
        band=f.get("band", ""),
        mode=mode,
        freq_mhz=freq,
        rst_sent=f.get("rst_sent", ""),
        rst_rcvd=f.get("rst_rcvd", ""),
        gridsquare=f.get("gridsquare", ""),
        station_callsign=f.get("station_callsign", ""),
        my_gridsquare=f.get("my_gridsquare", ""),
        tx_pwr_w=pwr,
        qso_date_off=f.get("qso_date_off", ""),
        time_off=f.get("time_off", ""),
        comment=f.get("comment", ""),
        extra=extra,
    )


# --- per-day ADIF files -------------------------------------------------

def daily_path(base_dir: Path, qso_date: str) -> Path:
    """Path of the dated ADIF file for a QSO date (``YYYYMMDD``)."""
    return Path(base_dir) / f"digiham_{qso_date}.adi"


def append_qso_file(path: Path, q: Qso) -> None:
    """Append one QSO to a standalone ADIF file, writing a header if new.

    Used for the optional per-day log files: plain append-only ADIF written
    alongside the main log. Raises OSError on write failure.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a") as f:
        if new_file:
            f.write(adif_header())
        f.write(qso_to_adif(q) + "\n")
