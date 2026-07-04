"""Qt wrapper around :class:`digiham.rigctl.RigctlClient`.

All socket traffic runs on a dedicated worker thread so a slow or wedged
rig never blocks the GUI. The GUI drives it through queued signals and
receives state back through Qt signals.

Split operation, as WSJT-X uses it, keeps the transmitted audio tone in a
comfortable part of the SSB passband: VFO B (Tx) is offset so the RF stays
put while the audio tone sits near the middle of the filter. Here we take
the simpler, robust route of setting the Tx dial so ``rf = dial + tx_audio``
lands on the same RF as the Rx tone.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .rigctl import RigctlClient, RigctldError


class _RigWorker(QObject):
    connected = Signal(bool, str)             # ok, message
    status = Signal(str)
    telemetry = Signal(float, str, bool)      # rx dial Hz, mode, ptt
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._client: RigctlClient | None = None
        self._split = False
        self._mode = ""

    @Slot(str, int, bool, str)
    def do_connect(self, host: str, port: int, split: bool, mode: str) -> None:
        self._split = split
        self._mode = mode
        try:
            self._client = RigctlClient(host, port)
            self._client.connect()
            if mode:
                try:
                    self._client.set_mode(mode, 0)
                except RigctldError:
                    pass
            freq = self._client.get_freq()
            self.connected.emit(True, f"connected to {host}:{port}")
            self.telemetry.emit(freq, mode, False)
        except (OSError, RigctldError, ValueError) as e:
            self._client = None
            self.connected.emit(False, str(e))

    @Slot()
    def do_disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.set_ptt(False)
            except Exception:
                pass
            self._client.close()
            self._client = None
        self.connected.emit(False, "disconnected")

    @Slot(float)
    def do_set_freq(self, hz: float) -> None:
        if self._client is None:
            return
        try:
            self._client.set_freq(hz)
        except (OSError, RigctldError) as e:
            self.failed.emit(f"set freq: {e}")

    @Slot(str)
    def do_set_mode(self, mode: str) -> None:
        if self._client is None or not mode:
            return
        self._mode = mode
        try:
            self._client.set_mode(mode, 0)
        except (OSError, RigctldError) as e:
            self.failed.emit(f"set mode: {e}")

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
                    except RigctldError:
                        pass
            else:
                self._client.set_split_vfo(False, "VFOA")
        except (OSError, RigctldError) as e:
            self.failed.emit(f"split: {e}")

    @Slot(bool)
    def do_set_ptt(self, on: bool) -> None:
        if self._client is None:
            return
        try:
            self._client.set_ptt(on)
        except (OSError, RigctldError) as e:
            self.failed.emit(f"ptt: {e}")

    @Slot()
    def do_poll(self) -> None:
        if self._client is None:
            return
        try:
            freq = self._client.get_freq()
            mode, _ = self._client.get_mode()
            ptt = self._client.get_ptt()
            self.telemetry.emit(freq, mode, ptt)
        except (OSError, RigctldError):
            pass


class RigController(QObject):
    """GUI-facing rig controller. Owns the worker thread."""

    connected = Signal(bool, str)
    status = Signal(str)
    telemetry = Signal(float, str, bool)
    failed = Signal(str)

    _req_connect = Signal(str, int, bool, str)
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

    def connect_rig(self, host: str, port: int, split: bool, mode: str) -> None:
        self._req_connect.emit(host, port, split, mode)

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
        try:
            self._req_disconnect.emit()
        except Exception:
            pass
        self._thread.quit()
        self._thread.wait(2000)
