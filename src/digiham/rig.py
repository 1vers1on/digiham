"""Qt wrapper around :class:`digiham.rigctl.RigctlClient`.

All socket traffic runs on a dedicated worker thread so a slow or wedged
rig never blocks the GUI. The GUI drives it through queued signals and
receives state back through Qt signals.

Each poll reports frequency/mode/PTT plus whichever meters the rig
supports (discovered once at connect): S-meter while receiving, SWR /
power / ALC while transmitting, supply voltage always.

Split operation, as WSJT-X uses it, keeps the transmitted audio tone in a
comfortable part of the SSB passband: VFO B (Tx) is offset so the RF stays
put while the audio tone sits near the middle of the filter. The engine
computes that offset; this module just applies it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, Signal, Slot

from . import serialports
from .rigctl import (
    ManagedRigctld, RigctlClient, RigctldError, RigctldStartError, normalize_mode,
)

logger = logging.getLogger(__name__)


@dataclass
class RigConnect:
    """Everything the worker needs to bring a rig connection up.

    Bundled into one object so it can ride a single Qt signal instead of a
    long positional argument list.
    """
    host: str = "localhost"
    port: int = 4532
    split: bool = True
    mode: str = ""
    # managed (private) rigctld — when set, host/port are chosen by us
    managed: bool = False
    model: int = 1
    device: str = ""
    baud: int = 0
    rigctld_path: str = ""

# Hamlib level names for the meters we poll, keyed by the name used in the
# meters dict. Split by when they are meaningful.
_METERS_RX = {"strength": "STRENGTH"}
_METERS_TX = {"power_w": "RFPOWER_METER_WATTS", "swr": "SWR", "alc": "ALC"}
_METERS_ALWAYS = {"vd": "VD_METER"}


class _RigWorker(QObject):
    connected = Signal(bool, str)             # ok, message
    status = Signal(str)
    telemetry = Signal(float, str, bool)      # rx dial Hz, mode, ptt
    meters = Signal(object)                   # {"ptt": bool, "swr": ..., ...}
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._client: RigctlClient | None = None
        self._managed: ManagedRigctld | None = None
        self._split = False
        self._mode = ""
        self._meter_names: dict[str, str] = {}
        self._poll_fails = 0

    @Slot(object)
    def do_connect(self, req: RigConnect) -> None:
        self._split = req.split
        self._mode = req.mode
        self._poll_fails = 0
        # clear out any daemon/client left over from a previous attempt
        self._stop_managed()

        host, port = req.host, req.port
        if req.managed:
            device, needs = serialports.resolve_device(req.device)
            if needs and not device:
                # "auto" but nothing suitable is plugged in yet
                self.connected.emit(False, "no serial device found")
                return
            try:
                self._managed = ManagedRigctld(
                    req.model, device, req.baud,
                    rigctld_path=req.rigctld_path)
                host, port = self._managed.start()
            except (OSError, RigctldStartError) as e:
                self._stop_managed()
                logger.exception("failed to start managed rigctld")
                self.connected.emit(False, f"rigctld: {e}")
                return

        try:
            logger.info("connecting to rigctld at %s:%s", host, port)
            self._client = RigctlClient(host, port)
            self._client.connect()
            if req.mode:
                try:
                    self._ensure_mode(req.mode)
                except (RigctldError, ValueError) as e:
                    logger.warning("failed to set rig mode during connect: %s", e)
                    self.failed.emit(f"set mode: {e}")
            freq = self._client.get_freq()
            real_mode, _width = self._client.get_mode()
            self._discover_meters()
            self.connected.emit(True, f"connected to {host}:{port}")
            self.telemetry.emit(freq, real_mode, False)
        except (OSError, RigctldError, ValueError) as e:
            self._client = None
            self._stop_managed()
            logger.exception("rig connection failed")
            self.connected.emit(False, str(e))

    def _stop_managed(self) -> None:
        if self._managed is not None:
            self._managed.stop()
            self._managed = None

    def _discover_meters(self) -> None:
        """Probe once which meters this rig can report."""
        self._meter_names = {}
        assert self._client is not None
        for key, name in {**_METERS_ALWAYS, **_METERS_RX, **_METERS_TX}.items():
            try:
                self._client.get_level(name)
                self._meter_names[key] = name
            except RigctldError:
                pass

    @Slot()
    def do_disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.set_ptt(False)
            except Exception:
                pass
            self._client.close()
            self._client = None
        self._stop_managed()
        logger.info("rig disconnected")
        self.connected.emit(False, "disconnected")

    @Slot(float)
    def do_set_freq(self, hz: float) -> None:
        if self._client is None:
            return
        try:
            self._client.set_freq(hz)
        except (OSError, RigctldError) as e:
            logger.warning("failed to set rig frequency to %s: %s", hz, e)
            self.failed.emit(f"set freq: {e}")

    @Slot(str)
    def do_set_mode(self, mode: str) -> None:
        if self._client is None or not mode:
            return
        self._mode = mode
        try:
            self._ensure_mode(mode)
        except (OSError, RigctldError, ValueError) as e:
            logger.warning("failed to set rig mode to %s: %s", mode, e)
            self.failed.emit(f"set mode: {e}")

    def _ensure_mode(self, mode: str) -> None:
        """Set *mode* only if the rig isn't already in it — mode changes are
        slow on some rigs (~2.5 s on an FTDX-10) and churn the passband."""
        assert self._client is not None
        try:
            current, _ = self._client.get_mode()
        except (OSError, RigctldError):
            current = ""
        if current != normalize_mode(mode):
            self._client.set_mode(mode, 0)

    @Slot(bool, float)
    def do_set_split(self, split: bool, tx_dial_hz: float) -> None:
        if self._client is None:
            return
        self._split = split
        try:
            if split and tx_dial_hz > 0:
                self._client.set_split_vfo(True, "VFOB")
                self._client.set_split_freq(tx_dial_hz)
                if self._mode:
                    try:
                        self._client.set_split_mode(self._mode, 0)
                    except (RigctldError, ValueError):
                        pass
            else:
                self._client.set_split_vfo(False, "VFOA")
        except (OSError, RigctldError) as e:
            logger.warning("failed to set split %s at %s: %s", split, tx_dial_hz, e)
            self.failed.emit(f"split: {e}")

    @Slot(bool)
    def do_set_ptt(self, on: bool) -> None:
        if self._client is None:
            return
        try:
            self._client.set_ptt(on)
        except (OSError, RigctldError) as e:
            logger.warning("failed to set ptt %s: %s", on, e)
            self.failed.emit(f"ptt: {e}")

    @Slot()
    def do_poll(self) -> None:
        if self._client is None:
            return
        try:
            freq = self._client.get_freq()
            mode, _ = self._client.get_mode()
            ptt = self._client.get_ptt()
        except (OSError, RigctldError) as e:
            # one hiccup is survivable (the client resyncs itself), but a
            # dead rigctld should be reported instead of silently ignored
            self._poll_fails += 1
            if self._poll_fails >= 3:
                logger.warning("rig connection lost after repeated poll failures: %s", e)
                self._drop(f"rig connection lost: {e}")
            return
        self._poll_fails = 0
        self.telemetry.emit(freq, mode, ptt)
        self.meters.emit(self._read_meters(ptt))

    def _read_meters(self, ptt: bool) -> dict:
        out: dict = {"ptt": ptt}
        wanted = dict(_METERS_ALWAYS)
        wanted.update(_METERS_TX if ptt else _METERS_RX)
        for key in wanted:
            name = self._meter_names.get(key)
            if name is None:
                continue
            try:
                out[key] = self._client.get_level(name)
            except (OSError, RigctldError):
                pass
        return out

    def _drop(self, msg: str) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        self._stop_managed()
        self.connected.emit(False, msg)


class RigController(QObject):
    """GUI-facing rig controller. Owns the worker thread."""

    connected = Signal(bool, str)
    status = Signal(str)
    telemetry = Signal(float, str, bool)
    meters = Signal(object)
    failed = Signal(str)

    _req_connect = Signal(object)
    _req_disconnect = Signal()
    _req_set_freq = Signal(float)
    _req_set_mode = Signal(str)
    _req_set_split = Signal(bool, float)
    _req_set_ptt = Signal(bool)
    _req_poll = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._thread.setObjectName("rigctld")
        self._worker = _RigWorker()
        self._worker.moveToThread(self._thread)

        self._worker.connected.connect(self.connected)
        self._worker.status.connect(self.status)
        self._worker.telemetry.connect(self.telemetry)
        self._worker.meters.connect(self.meters)
        self._worker.failed.connect(self.failed)

        self._req_connect.connect(self._worker.do_connect)
        self._req_disconnect.connect(self._worker.do_disconnect)
        self._req_set_freq.connect(self._worker.do_set_freq)
        self._req_set_mode.connect(self._worker.do_set_mode)
        self._req_set_split.connect(self._worker.do_set_split)
        self._req_set_ptt.connect(self._worker.do_set_ptt)
        self._req_poll.connect(self._worker.do_poll)

        self._connected = False
        self.connected.connect(self._on_connected)
        self._thread.start()

    def _on_connected(self, ok: bool, _msg: str) -> None:
        self._connected = ok

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -- public API (thread-safe, queued) --------------------------------

    def connect_rig(self, req: RigConnect) -> None:
        self._req_connect.emit(req)

    def disconnect_rig(self) -> None:
        self._req_disconnect.emit()

    def set_freq(self, hz: float) -> None:
        self._req_set_freq.emit(hz)

    def set_mode(self, mode: str) -> None:
        self._req_set_mode.emit(mode)

    def set_split(self, split: bool, tx_dial_hz: float) -> None:
        self._req_set_split.emit(split, tx_dial_hz)

    def set_ptt(self, on: bool) -> None:
        self._req_set_ptt.emit(on)

    def poll(self) -> None:
        self._req_poll.emit()

    def shutdown(self) -> None:
        # run do_disconnect synchronously so queued work (incl. any pending
        # PTT release) is processed before the thread goes down
        try:
            QMetaObject.invokeMethod(
                self._worker, "do_disconnect",
                Qt.ConnectionType.BlockingQueuedConnection)
        except Exception:
            pass
        self._thread.quit()
        self._thread.wait(2000)
