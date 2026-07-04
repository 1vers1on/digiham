"""Persistent configuration for digiham.

Settings live in a single JSON file under the platform's per-user config
directory:

* Linux/BSD: ``$XDG_CONFIG_HOME/digiham`` (default ``~/.config/digiham``)
* macOS: ``~/Library/Application Support/digiham``
* Windows: ``%APPDATA%\\digiham`` (default ``~\\AppData\\Roaming\\digiham``)

The :class:`Config` dataclass is the in-memory model; :func:`load` and
:meth:`Config.save` round-trip it to disk. Unknown keys in the file are
ignored so old configs keep loading after new fields are added.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _platform_config_base() -> Path:
    """Return the platform's per-user config base directory.

    The ``digiham`` subdirectory is appended by :func:`config_dir`.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base)
        return Path.home() / "AppData" / "Roaming"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    # Linux, *BSD and anything else: follow the XDG Base Directory spec.
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base)
    return Path.home() / ".config"


def config_dir() -> Path:
    d = _platform_config_base() / "digiham"
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
    tx_power_from_rig: bool = True  # log the rig's measured Tx power when it
                                    # can be read; else fall back to tx_power_dbm

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
    rig_mode: str = "PKTUSB"      # Hamlib mode to force on connect ("" = leave);
                                   # PKTUSB is DATA-U/DATA-USB on the radio's panel
    ptt_method: str = "rigctld"   # rigctld | vox | none

    # rigctld source: run our own private daemon or talk to an external one.
    # When rig_managed is True, host/port above are ignored and digiham
    # launches rigctld itself on a free loopback port.
    rig_managed: bool = False
    rigctld_path: str = ""        # "" = auto-locate the rigctld binary
    rig_model: int = 1            # Hamlib model number (1 = Dummy; see rigctld -l)
    # serial/USB device for the built-in rigctld:
    #   "auto" -> auto-detect the radio's USB-serial port (survives replug)
    #   ""     -> none (network / SDR rigs that need no serial port)
    #   else   -> an explicit path, e.g. /dev/ttyUSB0 or COM3
    rig_device: str = "auto"
    rig_baud: int = 0             # serial speed (0 = rigctld/backend default)

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
    disable_tx_after_qso: bool = False  # turn Tx off once a QSO completes (73/RR73)
    tx_watchdog_min: int = 6       # halt Tx after N minutes of no reply (0 = off)

    # --- Contest ---------------------------------------------------------
    contest_mode: str = ""         # "" (normal) | "FD" (ARRL Field Day)
    fd_class: str = "1D"           # Field Day transmitter class, e.g. 1D, 3A
    fd_section: str = ""           # ARRL/RAC section, e.g. WI, EMA, DX
    double_click_qsy: bool = True  # double-click a decode sets Rx freq
    cq_only: bool = False          # band-activity filter: show CQ calls only
    cq73_only: bool = False        # band-activity filter: show CQ + 73/RR73 only
    hide_worked: bool = False      # band-activity filter: hide calls worked B4
    snr_squelch: bool = False      # band-activity filter: visual squelch on SNR
    snr_squelch_db: int = -24      # hide decodes weaker than this (dB)

    # --- Alerts ----------------------------------------------------------
    sound_alerts: bool = False     # beep on the events below
    alert_new_dxcc: bool = True    # flag/alert stations from an unworked DXCC
    alert_new_grid: bool = False   # flag/alert stations from an unworked grid

    # --- Reporting -------------------------------------------------------
    pskreporter: bool = False
    all_txt: bool = True           # append decodes/Tx to an ALL.TXT spot log
    all_txt_file: str = ""         # "" -> config_dir()/ALL.TXT

    # --- WSJT-X UDP output (GridTracker, JTAlert, …) ---------------------
    udp_enabled: bool = False
    udp_host: str = "127.0.0.1"    # unicast address or multicast group
    udp_port: int = 2237           # WSJT-X default UDP server port
    udp_id: str = "digiham"        # WSJT-X instance id companions key off

    # --- UI --------------------------------------------------------------
    theme: str = "Default Dark"    # key into gui.theme.available_themes()
    waterfall_palette: str = "blue"
    waterfall_gain: float = 1.0
    waterfall_zero: float = 0.0
    font_size: int = 11
    show_bandactivity: bool = True

    # --- ADIF/log --------------------------------------------------------
    log_file: str = ""            # "" -> config_dir()/digiham_log.adi
    adif_daily_files: bool = False  # also write a dated ADIF per operating day
    adif_daily_dir: str = ""      # "" -> config_dir(); folder for the dated files

    # --- Plugins ---------------------------------------------------------
    plugins_enabled: bool = True
    plugins_dir: str = ""         # "" -> config_dir()/plugins
    disabled_plugins: list = field(default_factory=list)  # plugin names to skip

    # Free-form extras that we do not model explicitly.
    extra: dict = field(default_factory=dict)

    def resolved_log_file(self) -> Path:
        return Path(self.log_file) if self.log_file else log_path()

    def resolved_all_txt(self) -> Path:
        return Path(self.all_txt_file) if self.all_txt_file \
            else config_dir() / "ALL.TXT"

    def resolved_daily_dir(self) -> Path:
        return Path(self.adif_daily_dir) if self.adif_daily_dir else config_dir()

    def resolved_plugins_dir(self) -> Path:
        return Path(self.plugins_dir) if self.plugins_dir \
            else config_dir() / "plugins"

    def fd_exchange(self) -> str:
        """Field Day exchange ``"<class> <section>"`` (empty if incomplete)."""
        cls = self.fd_class.strip().upper()
        sect = self.fd_section.strip().upper()
        return f"{cls} {sect}" if cls and sect else ""

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
