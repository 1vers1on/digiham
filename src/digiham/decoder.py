"""Background decoding.

FT8/FT4/WSPR decoding can take a second or more, so it runs on its own
thread. The engine feeds it period-aligned audio slices (partial or full)
and gets :class:`ft8lib.Decode` lists back through a Qt signal. The
callsign hash tables live here and persist across cycles so hashed calls
resolve over time.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot

import ft8lib


class _DecodeWorker(QObject):
    decoded = Signal(object, object)      # (list[Decode], meta dict)
    busychanged = Signal(bool)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.hashes = ft8lib.HashTable()
        self.wspr_hashes = ft8lib.WsprHashTable()

    @Slot(object)
    def run_job(self, job: dict) -> None:
        self.busychanged.emit(True)
        t0 = time.monotonic()
        try:
            results = self._decode(job)
        except Exception as e:                     # never kill the thread
            results = []
            self.failed.emit(f"decode error: {e}")
        meta = dict(job)
        meta.pop("audio", None)
        meta["elapsed"] = time.monotonic() - t0
        self.decoded.emit(results, meta)
        self.busychanged.emit(False)

    def _decode(self, job: dict) -> list:
        audio = job["audio"]
        mode = job["mode"]
        fmin = float(job.get("freq_min", 200))
        fmax = float(job.get("freq_max", 3500))
        depth = int(job.get("depth", 3))
        mycall = job.get("mycall", "")
        dxcall = job.get("dxcall", "")
        if mode == "FT8":
            return ft8lib.decode_ft8(
                audio, freq_min=fmin, freq_max=fmax, depth=depth,
                hashes=self.hashes, mycall=mycall, dxcall=dxcall)
        if mode == "FT4":
            return ft8lib.decode_ft4(
                audio, freq_min=fmin, freq_max=fmax, depth=depth,
                hashes=self.hashes, mycall=mycall, dxcall=dxcall)
        if mode == "WSPR":
            fmin = max(1350.0, min(fmin, 1610.0)) if fmin > 1000 else 1400.0
            fmax = 1600.0 if fmax < 1300 else min(fmax, 1650.0)
            return ft8lib.decode_wspr(audio, hashes=self.wspr_hashes)
        return []

    @Slot(str, str)
    def prime_station(self, mycall: str, dxcall: str) -> None:
        try:
            self.hashes.set_station(mycall, dxcall)
        except Exception:
            pass


class DecodeController(QObject):
    """GUI-facing decode controller; owns the worker thread."""

    decoded = Signal(object, object)
    busychanged = Signal(bool)
    failed = Signal(str)

    _req_job = Signal(object)
    _req_prime = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._thread.setObjectName("decoder")
        self._worker = _DecodeWorker()
        self._worker.moveToThread(self._thread)

        self._worker.decoded.connect(self.decoded)
        self._worker.busychanged.connect(self._on_busy)
        self._worker.failed.connect(self.failed)
        self._req_job.connect(self._worker.run_job)
        self._req_prime.connect(self._worker.prime_station)

        self._busy = False
        self._thread.start()

    def _on_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busychanged.emit(busy)

    @property
    def busy(self) -> bool:
        return self._busy

    def submit(self, job: dict) -> bool:
        """Queue a decode job; drops it if a decode is already running.

        ``_busy`` is set optimistically here rather than waiting for the
        worker's queued ``busychanged`` signal, so a fast caller can't slip
        several jobs in before the flag flips.
        """
        if self._busy:
            return False
        self._busy = True
        self._req_job.emit(job)
        return True

    def prime_station(self, mycall: str, dxcall: str) -> None:
        self._req_prime.emit(mycall, dxcall)

    def shutdown(self) -> None:
        self._thread.quit()
        self._thread.wait(2000)
