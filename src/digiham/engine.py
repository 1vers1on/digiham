"""The :class:`RadioEngine` — digiham's clock, scheduler and glue.

It owns the receive/transmit cycle timing (aligned to UTC), the audio
capture and playback, the decode worker, the rig controller, the QSO
auto-sequencer and the ADIF log, and exposes a tidy Qt-signal surface for
the GUI. Nothing here touches widgets, so the whole operating core can be
driven headless or tested on its own.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

import ft8lib

from . import bands
from . import geo
from .adif import Qso, QsoLog
from .audio import Capture, TxPlayer
from .config import Config
from .decoder import DecodeController
from .rig import RigController
from . import sequencer as seq


# Per-mode timing/geometry.
@dataclass(frozen=True)
class _ModeSpec:
    period: float
    tx_offset: float
    nmax: int
    tx_start_sample: int
    early: Optional[float]      # seconds into cycle for the early decode

MODES = {
    "FT8": _ModeSpec(15.0, 0.5, ft8lib.FT8.NMAX, 6000, 13.6),
    "FT4": _ModeSpec(7.5, 0.5, ft8lib.FT4.NMAX, 6000, 5.7),
    "WSPR": _ModeSpec(120.0, 1.0, ft8lib.WSPR.NMAX, 12000, None),
}


@dataclass
class DecodeRow:
    """An enriched decode ready for display and logging."""
    time_utc: float
    cycle: int
    mode: str
    band: str
    message: str
    snr: float
    dt: float
    freq_audio: float
    rf_hz: float
    drift: float = 0.0
    to_me: bool = False
    is_cq: bool = False
    directed_cq: str = ""
    de: str = ""
    grid: str = ""
    worked_before: bool = False
    new_call: bool = False
    distance_km: Optional[float] = None
    bearing_deg: Optional[float] = None
    parsed: seq.ParsedMessage = field(default_factory=lambda: seq.ParsedMessage(""))

    @property
    def utc_hhmmss(self) -> str:
        return dt.datetime.fromtimestamp(self.time_utc, dt.timezone.utc).strftime("%H%M%S")


class RadioEngine(QObject):
    # decode / activity
    decodesReady = Signal(object)         # list[DecodeRow]
    newCycle = Signal(int)                # cycle index rollover
    cycleTick = Signal(float, int)        # fraction 0..1, cycle index
    spectrum = Signal(object, float)      # magnitudes (dB), bin Hz
    decoderBusy = Signal(bool)
    audioLevel = Signal(float)

    # station / operating state
    statusMessage = Signal(str)
    txStateChanged = Signal(bool, str)    # transmitting?, message
    txEnableChanged = Signal(bool)
    txMessagesChanged = Signal(object, int)   # list[str], next idx
    sequencerState = Signal(object)       # dict
    freqChanged = Signal(int, int)        # rx audio, tx audio
    rigState = Signal(bool, float, str)   # connected, dial Hz, mode
    rigMeters = Signal(object)            # dict from RigController.meters
    bandChanged = Signal(str)             # band followed the rig dial
    dialChanged = Signal(float)
    qsoLogged = Signal(object)            # Qso

    _txFinished = Signal(int)

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.mode = cfg.mode if cfg.mode in MODES else "FT8"
        self.band = cfg.band
        self.dial_hz = float(bands.dial_for(self.band, self.mode) or 14_074_000)
        self.rx_freq = cfg.rx_freq
        self.tx_freq = cfg.tx_freq
        self.tx_enabled = False

        self.log = QsoLog(cfg.resolved_log_file())
        self.seq = seq.Sequencer(cfg.my_call, cfg.my_grid)

        self.capture: Optional[Capture] = None
        self.tx = TxPlayer(cfg.audio_out, cfg.tx_audio_level)
        self.decoder = DecodeController(self)
        self.rig = RigController(self)

        self._txing = False
        self._tx_cycle = -1
        self._tx_idx = 0
        self._watchdog_deadline = 0.0
        self._qso_time_on: Optional[float] = None

        self._jobq: list[dict] = []
        self._dispatched: set[tuple] = set()
        self._seen: dict[int, set] = {}
        self._cur_cycle = -1
        self._rig_poll_t = 0.0
        self._rig_want = False        # user wants the rig connected
        self._rig_retry_t = 0.0
        self.monitoring = True

        # wiring
        self.decoder.decoded.connect(self._on_decoded)
        self.decoder.busychanged.connect(self.decoderBusy)
        self.decoder.failed.connect(self.statusMessage)
        self.rig.connected.connect(self._on_rig_connected)
        self.rig.telemetry.connect(self._on_rig_telemetry)
        self.rig.meters.connect(self.rigMeters)
        self.rig.failed.connect(self.statusMessage)
        self._txFinished.connect(self._on_tx_finished)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(50)
        self._tick_timer.timeout.connect(self._tick)
        self._spec_timer = QTimer(self)
        self._spec_timer.setInterval(80)
        self._spec_timer.timeout.connect(self._emit_spectrum)

    # ------------------------------------------------------------------ #
    # properties
    # ------------------------------------------------------------------ #

    @property
    def spec(self) -> _ModeSpec:
        return MODES[self.mode]

    @property
    def period(self) -> float:
        return self.spec.period

    def current_dial(self) -> float:
        return self.dial_hz

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        self._start_capture()
        if self.cfg.rig_enabled:
            self.connect_rig()
        self._tick_timer.start()
        self._spec_timer.start()
        self._emit_tx_messages()
        self._emit_seq_state()
        self.freqChanged.emit(self.rx_freq, self.tx_freq)
        self.dialChanged.emit(self.dial_hz)

    def stop(self) -> None:
        self._tick_timer.stop()
        self._spec_timer.stop()
        if self._txing:
            self._end_tx()
        if self.capture:
            self.capture.stop()
        self.tx.stop()
        self.rig.shutdown()
        self.decoder.shutdown()

    def _start_capture(self) -> None:
        try:
            self.capture = Capture(
                self.cfg.audio_in, self.cfg.audio_in_gain,
                seconds=max(135.0, self.period + 15.0),
                on_status=self.statusMessage.emit)
            self.capture.start(time.time())
            self.statusMessage.emit(f"Rx audio {self.capture.fs} Hz")
        except Exception as e:
            self.capture = None
            self.statusMessage.emit(f"audio input unavailable: {e}")

    def restart_audio(self) -> None:
        if self.capture:
            self.capture.stop()
        self.tx = TxPlayer(self.cfg.audio_out, self.cfg.tx_audio_level)
        self._start_capture()

    # ------------------------------------------------------------------ #
    # operating controls
    # ------------------------------------------------------------------ #

    def set_mode(self, mode: str) -> None:
        if mode not in MODES or mode == self.mode:
            return
        self.halt_tx()
        self.mode = mode
        self.cfg.mode = mode
        self.set_band(self.band, force=True)
        self._dispatched.clear()
        self.seq.start_cq()
        self._emit_tx_messages()
        self.statusMessage.emit(f"mode {mode}")

    def set_band(self, band: str, force: bool = False) -> None:
        if band not in bands.BANDS:
            return
        if band == self.band and not force:
            return
        self.band = band
        self.cfg.band = band
        dial = bands.dial_for(band, self.mode)
        if dial is None:
            self.statusMessage.emit(f"{self.mode} has no standard freq on {band}")
            return
        self.dial_hz = float(dial)
        self.dialChanged.emit(self.dial_hz)
        if self.rig.is_connected:
            self.rig.set_freq(self.dial_hz)
            if self.cfg.rig_mode:
                self.rig.set_mode(self.cfg.rig_mode)
        self.statusMessage.emit(f"{band}  {self.dial_hz/1e6:.6f} MHz")

    def set_rx_freq(self, hz: int) -> None:
        hz = int(max(200, min(4000, hz)))
        self.rx_freq = hz
        self.cfg.rx_freq = hz
        if self.cfg.lock_tx_rx and not self.cfg.hold_tx_freq:
            self.tx_freq = hz
            self.cfg.tx_freq = hz
        self.freqChanged.emit(self.rx_freq, self.tx_freq)

    def set_tx_freq(self, hz: int) -> None:
        hz = int(max(200, min(4000, hz)))
        self.tx_freq = hz
        self.cfg.tx_freq = hz
        self.freqChanged.emit(self.rx_freq, self.tx_freq)

    def enable_tx(self, on: bool) -> None:
        self.tx_enabled = on
        if on:
            self._watchdog_deadline = time.time() + self.cfg.tx_watchdog_min * 60
        self.txEnableChanged.emit(on)
        self.statusMessage.emit("Tx enabled" if on else "Tx disabled")

    def halt_tx(self) -> None:
        self.tx_enabled = False
        if self._txing:
            self._end_tx()
        self.txEnableChanged.emit(False)

    def set_tx_odd(self, odd: bool) -> None:
        self.cfg.tx_odd = odd

    def select_tx(self, idx: int) -> None:
        self.seq.select_tx(idx)
        self.txMessagesChanged.emit(list(self.seq.messages), self.seq.next_tx)

    def override_message(self, idx: int, text: str) -> None:
        """Replace one Tx slot with custom/free text (until the next QSO change)."""
        if 1 <= idx <= 6:
            self.seq.messages[idx - 1] = text.strip().upper()[:37]
            self.txMessagesChanged.emit(list(self.seq.messages), self.seq.next_tx)

    def set_free_text(self, text: str) -> None:
        self.override_message(5, text)
        self.seq.select_tx(5)
        self.txMessagesChanged.emit(list(self.seq.messages), self.seq.next_tx)

    def set_monitor(self, on: bool) -> None:
        self.monitoring = on
        if on and self.capture is None:
            self._start_capture()
        elif not on and self.capture is not None:
            self.capture.stop()
            self.capture = None
        self.statusMessage.emit("monitoring" if on else "monitor off")

    def start_cq(self) -> None:
        self.seq.start_cq()
        self._emit_tx_messages()
        self._emit_seq_state()

    def set_dx(self, dxcall: str, dxgrid: str = "") -> None:
        """Arm a DX call manually (as if typed into the DX Call box)."""
        if dxcall:
            self.seq.answer_cq(dxcall, dxgrid, self._last_snr_for(dxcall))
            self.decoder.prime_station(self.cfg.my_call, dxcall)
            self._qso_time_on = time.time()
            self._emit_tx_messages()
            self._emit_seq_state()

    def _last_snr_for(self, _call: str) -> int:
        return 0

    def double_click_decode(self, row: DecodeRow) -> None:
        if self.cfg.double_click_qsy and not self.cfg.hold_tx_freq:
            self.set_rx_freq(int(round(row.freq_audio)))
        if not row.de or seq.same_call(row.de, self.cfg.my_call):
            return
        log = None
        if row.to_me:
            # They are already working us — reply with the *right* next
            # message for what they sent (a report if they answered our CQ
            # with a grid, a roger if they reported us, and so on) instead of
            # blindly resending our grid.
            log = self.seq.engage(row.parsed, row.snr)
        else:
            # They are calling CQ (or working someone else) and we want to
            # answer them: we become the caller and open with our grid.
            self.seq.answer_cq(row.de, row.grid, row.snr)
        self.decoder.prime_station(self.cfg.my_call, row.de)
        self._qso_time_on = self._qso_time_on or time.time()
        self.enable_tx(True)
        if log and self.cfg.auto_log:
            self._commit_log(log.dxcall, log.dxgrid, log.report_sent, log.report_recv)
        self._emit_tx_messages()
        self._emit_seq_state()

    def log_current_qso(self) -> None:
        s = self.seq
        if not s.dxcall:
            self.statusMessage.emit("no QSO to log")
            return
        self._commit_log(s.dxcall, s.dxgrid, s.report_out, s.report_in)

    # ------------------------------------------------------------------ #
    # rig
    # ------------------------------------------------------------------ #

    def connect_rig(self) -> None:
        self._rig_want = True
        self._rig_retry_t = time.time()
        self.rig.connect_rig(self.cfg.rig_host, self.cfg.rig_port,
                             self.cfg.rig_split, self.cfg.rig_mode)

    def disconnect_rig(self) -> None:
        self._rig_want = False
        self.rig.disconnect_rig()

    def _on_rig_connected(self, ok: bool, msg: str) -> None:
        self.statusMessage.emit(f"rig: {msg}")
        self.rigState.emit(ok, self.dial_hz, self.cfg.rig_mode)
        if ok:
            self.rig.set_freq(self.dial_hz)

    def _on_rig_telemetry(self, dial: float, mode: str, ptt: bool) -> None:
        if dial > 0 and abs(dial - self.dial_hz) > 1:
            self.dial_hz = dial
            self.dialChanged.emit(dial)
            # follow the rig: turning the knob onto another band switches
            # the app's band with it
            band = bands.band_for_freq(dial)
            if band and band != self.band:
                self.band = band
                self.cfg.band = band
                self.bandChanged.emit(band)
                self.statusMessage.emit(f"rig QSY → {band}")
        self.rigState.emit(True, dial, mode)

    # ------------------------------------------------------------------ #
    # main tick
    # ------------------------------------------------------------------ #

    def _tick(self) -> None:
        now = time.time()
        P = self.period
        cycle = int(now // P)
        cstart = cycle * P
        t = now - cstart

        if cycle != self._cur_cycle:
            self._cur_cycle = cycle
            self.newCycle.emit(cycle)
            self._prune(cycle)
        self.cycleTick.emit(min(1.0, t / P), cycle)

        if self.capture:
            self.audioLevel.emit(self.capture.level)

        if now - self._rig_poll_t > 1.0 and self.rig.is_connected:
            self._rig_poll_t = now
            self.rig.poll()
        if self._rig_want and not self.rig.is_connected \
                and now - self._rig_retry_t > 10.0:
            self._rig_retry_t = now
            self.statusMessage.emit("rig: reconnecting…")
            self.rig.connect_rig(self.cfg.rig_host, self.cfg.rig_port,
                                 self.cfg.rig_split, self.cfg.rig_mode)

        if self.monitoring:
            self._schedule_decodes(cycle, cstart, t)
            self._pump_jobs()
        self._maybe_transmit(cycle, cstart, t, now)

    def _prune(self, cycle: int) -> None:
        self._dispatched = {d for d in self._dispatched if d[0] >= cycle - 4}
        self._seen = {c: v for c, v in self._seen.items() if c >= cycle - 4}

    def _schedule_decodes(self, cycle: int, cstart: float, t: float) -> None:
        spec = self.spec
        # early decode of the current cycle (auto-seq needs it before Tx)
        if spec.early is not None and t >= spec.early:
            self._queue_decode(cycle, cstart, spec.early, "early")
        # authoritative full decode of the previous cycle, once it's complete
        if t >= 0.15:
            self._queue_decode(cycle - 1, (cycle - 1) * self.period,
                               self.period, "full")

    def _queue_decode(self, cycle: int, cstart: float, length: float, tag: str) -> None:
        key = (cycle, tag)
        if key in self._dispatched or cycle < 0 or self.capture is None:
            return
        self._dispatched.add(key)
        audio = self.capture.read_period(cstart, length)
        if audio is None:
            return
        fmin, fmax = self._decode_window()
        self._jobq.append({
            "audio": audio, "mode": self.mode, "band": self.band,
            "cycle": cycle, "cstart": cstart, "tag": tag,
            "freq_min": fmin, "freq_max": fmax,
            "depth": self.cfg.decode_depth,
            "mycall": self.cfg.my_call,
            "dxcall": self.seq.dxcall if self.cfg.decode_dxcall_ap else "",
        })

    def _decode_window(self) -> tuple[float, float]:
        if self.mode == "WSPR":
            return 1400.0, 1600.0
        return float(self.cfg.freq_min), float(self.cfg.freq_max)

    def _pump_jobs(self) -> None:
        while self._jobq and not self.decoder.busy:
            job = self._jobq.pop(0)
            if not self.decoder.submit(job):
                self._jobq.insert(0, job)
                break

    # ------------------------------------------------------------------ #
    # decode results
    # ------------------------------------------------------------------ #

    def _on_decoded(self, results: list, meta: dict) -> None:
        cycle = meta["cycle"]
        cstart = meta["cstart"]
        seen = self._seen.setdefault(cycle, set())
        rows: list[DecodeRow] = []
        worked = self.log.worked_calls()
        for r in results:
            if r.message in seen:
                continue
            seen.add(r.message)
            rows.append(self._make_row(r, cycle, cstart, worked))
        if rows:
            self.decodesReady.emit(rows)
            for row in rows:
                self._auto_sequence(row)
        self._pump_jobs()

    def _make_row(self, r, cycle: int, cstart: float, worked: set) -> DecodeRow:
        pm = seq.parse(r.message)
        rf = self.dial_hz + r.freq
        de_base = seq.base_call(pm.de) if pm.de else ""
        dist = bearing = None
        if pm.grid and self.cfg.my_grid:
            db = geo.distance_bearing(self.cfg.my_grid, pm.grid)
            if db is not None:
                dist, bearing = db
        row = DecodeRow(
            time_utc=cstart + self.spec.tx_offset,
            cycle=cycle, mode=self.mode, band=self.band, message=r.message,
            snr=r.snr, dt=r.dt, freq_audio=r.freq, rf_hz=rf,
            drift=getattr(r, "drift", 0.0),
            to_me=bool(self.cfg.my_call) and seq.same_call(pm.to, self.cfg.my_call),
            is_cq=pm.is_cq, directed_cq=pm.cq_dir, de=de_base, grid=pm.grid,
            worked_before=de_base in worked if de_base else False,
            new_call=bool(de_base) and de_base not in worked,
            distance_km=dist, bearing_deg=bearing,
            parsed=pm)
        return row

    def _auto_sequence(self, row: DecodeRow) -> None:
        if not self.cfg.auto_seq or not self.cfg.my_call:
            return
        if not row.to_me or not row.de or seq.same_call(row.de, self.cfg.my_call):
            return
        s = self.seq
        pm = row.parsed
        if s.in_qso and s.is_current_dx(pm):
            # A message from the station we are working — advance the QSO.
            # This keeps our role fixed and handles retries (a repeated
            # message just re-queues the same reply).
            self._apply_seq_result(s.on_decode(pm, row.snr))
        elif not s.in_qso and self.tx_enabled and self.cfg.call_first \
                and pm.kind in (seq.K_GRID, seq.K_REPORT):
            # A fresh caller is answering our CQ (a grid, or straight in with
            # a report). engage() infers that we are the CQ station and opens
            # with the correct reply.
            self._apply_seq_result(s.engage(pm, row.snr))
            self.decoder.prime_station(self.cfg.my_call, row.de)
        # Otherwise the message is addressed to us but we are busy with
        # another station (or not calling) — leave it for the operator.

    def _apply_seq_result(self, log: Optional[seq.LogRequest]) -> None:
        """Shared bookkeeping after the sequencer advances a QSO."""
        now = time.time()
        self._qso_time_on = self._qso_time_on or now
        if self.cfg.tx_watchdog_min:
            self._watchdog_deadline = now + self.cfg.tx_watchdog_min * 60
        self._emit_tx_messages()
        self._emit_seq_state()
        if log and self.cfg.auto_log:
            self._commit_log(log.dxcall, log.dxgrid, log.report_sent, log.report_recv)

    # ------------------------------------------------------------------ #
    # transmit
    # ------------------------------------------------------------------ #

    def _maybe_transmit(self, cycle: int, cstart: float, t: float, now: float) -> None:
        if self._txing or not self.tx_enabled or cycle == self._tx_cycle:
            return
        parity = cycle % 2
        want = 1 if self.cfg.tx_odd else 0
        if parity != want:
            return
        # trigger just after the cycle boundary, compensating for tick jitter
        if not (0.0 <= t <= 0.40):
            return
        if self.cfg.tx_watchdog_min and now > self._watchdog_deadline:
            self.statusMessage.emit("Tx watchdog: halting")
            self.halt_tx()
            return
        msg = self.seq.current_message()
        if not msg or not self.cfg.my_call:
            return
        self._tx_cycle = cycle
        self._begin_tx(msg, self.seq.next_tx, t)

    def _begin_tx(self, msg: str, idx: int, t_in_cycle: float) -> None:
        split_offset = self._split_offset()
        try:
            wave = self._render_tx(msg, self.tx_freq - split_offset)
        except Exception as e:
            self.statusMessage.emit(f"encode failed: {e}")
            return
        skip = int(max(0.0, t_in_cycle) * ft8lib.SAMPLE_RATE)
        if skip < len(wave):
            wave = wave[skip:]
        self._txing = True
        self._tx_idx = idx
        self._qso_time_on = self._qso_time_on or time.time()
        if self.rig.is_connected and self.cfg.ptt_method == "rigctld":
            if self.cfg.rig_split:
                self.rig.set_split(True, self.dial_hz + split_offset)
            self.rig.set_ptt(True)
        self.txStateChanged.emit(True, msg)
        self.statusMessage.emit(f"Tx: {msg}")
        try:
            self.tx.play(wave, on_done=lambda: self._txFinished.emit(idx))
        except Exception as e:
            self.statusMessage.emit(f"Tx audio failed: {e}")
            self._end_tx()

    def _split_offset(self) -> int:
        """WSJT-X style "fake it": shift the Tx dial in 500 Hz steps so the
        transmitted audio tone lands in the clean 1500–2000 Hz part of the
        passband while the RF stays put."""
        if not (self.cfg.rig_split and self.rig.is_connected
                and self.cfg.ptt_method == "rigctld"):
            return 0
        tone = self.tx_freq
        if 1500 <= tone < 2000:
            return 0
        return 500 * (tone // 500) - 1500

    def _render_tx(self, msg: str, f0: float) -> np.ndarray:
        spec = self.spec
        if self.mode == "FT8":
            body = ft8lib.encode_ft8(msg, f0=float(f0))
        elif self.mode == "FT4":
            body = ft8lib.encode_ft4(msg, f0=float(f0))
        else:
            wmsg = self._wspr_message()
            body = ft8lib.encode_wspr(wmsg, f0=float(f0 or 1500))
        tail = int(0.1 * ft8lib.SAMPLE_RATE)
        out = np.zeros(spec.tx_start_sample + len(body) + tail, dtype=np.float64)
        out[spec.tx_start_sample:spec.tx_start_sample + len(body)] = body
        return out

    def _wspr_message(self) -> str:
        grid = (self.cfg.my_grid or "AA00")[:4]
        return f"{self.cfg.my_call} {grid} {self.cfg.tx_power_dbm}"

    def _on_tx_finished(self, idx: int) -> None:
        self._end_tx()
        log = self.seq.on_transmitted(idx)
        self._emit_tx_messages()
        self._emit_seq_state()
        if log and self.cfg.auto_log:
            self._commit_log(log.dxcall, log.dxgrid, log.report_sent, log.report_recv)

    def _end_tx(self) -> None:
        self.tx.stop()
        if self.rig.is_connected and self.cfg.ptt_method == "rigctld":
            self.rig.set_ptt(False)
        self._txing = False
        self.txStateChanged.emit(False, "")

    # ------------------------------------------------------------------ #
    # logging
    # ------------------------------------------------------------------ #

    def _commit_log(self, dxcall: str, dxgrid: str,
                    report_sent: int, report_recv: Optional[int]) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        t_on = dt.datetime.fromtimestamp(self._qso_time_on or now.timestamp(),
                                         dt.timezone.utc)
        rf_mhz = (self.dial_hz + self.tx_freq) / 1e6
        q = Qso(
            call=dxcall, qso_date=t_on.strftime("%Y%m%d"),
            time_on=t_on.strftime("%H%M%S"),
            qso_date_off=now.strftime("%Y%m%d"), time_off=now.strftime("%H%M%S"),
            band=self.band, mode=self.mode, freq_mhz=rf_mhz,
            rst_sent=seq.fmt_report(report_sent),
            rst_rcvd=seq.fmt_report(report_recv) if report_recv is not None else "",
            gridsquare=dxgrid, station_callsign=self.cfg.my_call,
            my_gridsquare=self.cfg.my_grid,
            tx_pwr_w=round(10 ** ((self.cfg.tx_power_dbm - 30) / 10), 2),
            comment=f"{self.mode} {self.band}")
        if self.log.add(q):
            self.qsoLogged.emit(q)
            self.statusMessage.emit(f"logged {dxcall}")
        self._qso_time_on = None

    # ------------------------------------------------------------------ #
    # spectrum
    # ------------------------------------------------------------------ #

    def _emit_spectrum(self) -> None:
        if not self.capture:
            return
        raw = self.capture.latest(4096 / self.capture.fs)
        if raw is None or len(raw) < 256:
            return
        n = 1 << int(np.floor(np.log2(len(raw))))
        x = raw[-n:] * np.hanning(n)
        mag = np.abs(np.fft.rfft(x)) + 1e-9
        db = 20.0 * np.log10(mag)
        self.spectrum.emit(db.astype(np.float32), self.capture.fs / n)

    # ------------------------------------------------------------------ #
    # emitters
    # ------------------------------------------------------------------ #

    def _emit_tx_messages(self) -> None:
        self.seq.set_station(self.cfg.my_call, self.cfg.my_grid)
        self.txMessagesChanged.emit(list(self.seq.messages), self.seq.next_tx)

    def _emit_seq_state(self) -> None:
        s = self.seq
        self.sequencerState.emit({
            "in_qso": s.in_qso, "calling_cq": s.calling_cq,
            "dxcall": s.dxcall, "dxgrid": s.dxgrid,
            "report_out": s.report_out, "report_in": s.report_in,
            "next_tx": s.next_tx})

    def apply_config(self, cfg: Config) -> None:
        """Re-read settings that can change at runtime."""
        self.cfg = cfg
        self.seq.set_station(cfg.my_call, cfg.my_grid)
        self.seq.use_rr73 = True
        self.tx.level = cfg.tx_audio_level
        self._emit_tx_messages()
        self.freqChanged.emit(self.rx_freq, self.tx_freq)
