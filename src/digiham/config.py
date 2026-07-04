"""Persistent configuration for digiham.

Settings live in a single JSON file under the platform config directory
(``$XDG_CONFIG_HOME/digiham/config.json`` on Linux). The :class:`Config`
dataclass is the in-memory model; :func:`load` and :meth:`Config.save`
round-trip it to disk. Unknown keys in the file are ignored so old
configs keep loading after new fields are added.
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = Path(base) / "digiham"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


def log_path() -> Path:
    return config_dir() / "digiham_log.adi"


@dataclass
class Config:
    # --- Station ---------------------------------------------------------
    my_call: str = ""
    my_grid: str = ""
    tx_power_dbm: int = 37          # WSPR / logging power, dBm (37 dBm = 5 W)

    # --- Operating -------------------------------------------------------
    mode: str = "FT8"              # FT8 | FT4 | WSPR
    band: str = "20m"             # key into bands.BANDS
    tx_odd: bool = False           # transmit on odd (2nd) periods when True

    # --- Audio -----------------------------------------------------------
    audio_in: str = ""            # sounddevice input device name ("" = default)
    audio_out: str = ""           # sounddevice output device name
    audio_in_gain: float = 1.0
    tx_audio_level: float = 0.8    # 0..1 output amplitude

    # --- Radio (rigctld) -------------------------------------------------
    rig_enabled: bool = False
    rig_host: str = "localhost"
    rig_port: int = 4532
    rig_split: bool = True         # use split (Tx on VFO B) to keep audio in passband
    rig_mode: str = "USB"         # rig sideband mode to force on connect ("" = leave)
    ptt_method: str = "rigctld"   # rigctld | vox | none

    # --- Decoding --------------------------------------------------------
    decode_depth: int = 3
    freq_min: int = 200
    freq_max: int = 3500
    decode_dxcall_ap: bool = True  # feed DX call to decoder for a-priori digs

    # --- Frequencies (audio Hz within the passband) ----------------------
    rx_freq: int = 1500
    tx_freq: int = 1500
    lock_tx_rx: bool = True        # Tx freq follows Rx freq
    hold_tx_freq: bool = False

    # --- Behaviour -------------------------------------------------------
    auto_seq: bool = True          # run the QSO state machine automatically
    call_first: bool = False       # answer the first caller after a CQ
    auto_log: bool = True          # log automatically on RR73/73
    tx_watchdog_min: int = 6       # halt Tx after N minutes of no reply (0 = off)
    double_click_qsy: bool = True  # double-click a decode sets Rx freq
    cq_only: bool = False          # band-activity filter
    alert_new_dxcc: bool = True

    # --- Reporting -------------------------------------------------------
    pskreporter: bool = False

    # --- UI --------------------------------------------------------------
    waterfall_palette: str = "blue"
    waterfall_gain: float = 1.0
    waterfall_zero: float = 0.0
    font_size: int = 11
    show_bandactivity: bool = True

    # --- ADIF/log --------------------------------------------------------
    log_file: str = ""            # "" -> config_dir()/digiham_log.adi

    # Free-form extras that we do not model explicitly.
    extra: dict = field(default_factory=dict)

    def resolved_log_file(self) -> Path:
        return Path(self.log_file) if self.log_file else log_path()

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))
        tmp.replace(path)


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config()
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return Config()
    known = {f.name for f in dataclasses.fields(Config)}
    clean = {k: v for k, v in raw.items() if k in known}
    return Config(**clean)
