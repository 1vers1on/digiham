"""Sound-card I/O for digiham.

Capture runs a continuous input stream into a ring buffer tagged with an
absolute UTC time base, so any past receive period can be sliced out and
handed to the decoders exactly aligned to the mode's T/R cycle. Transmit
plays a pre-rendered waveform out of the chosen output device.

The library wants 12 kHz mono; if the device cannot open at 12 kHz we
capture at a supported rate and resample each period on the way out.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

import numpy as np

try:
    import sounddevice as sd
except Exception:                      # pragma: no cover - optional at import
    sd = None

try:
    from scipy.signal import resample_poly
except Exception:                      # pragma: no cover
    resample_poly = None

from ft8lib import SAMPLE_RATE          # 12000

_CANDIDATE_RATES = (12000, 48000, 24000, 44100, 16000)


# --- device enumeration --------------------------------------------------

def list_devices(kind: str) -> list[tuple[int, str]]:
    """Return ``(index, name)`` for input/output ('in'/'out') devices."""
    if sd is None:
        return []
    out = []
    try:
        devices = sd.query_devices()
    except Exception:
        return []
    for i, d in enumerate(devices):
        ch = d["max_input_channels"] if kind == "in" else d["max_output_channels"]
        if ch > 0:
            out.append((i, d["name"]))
    return out


def _device_index(name: str, kind: str) -> Optional[int]:
    if not name:
        return None
    for i, n in list_devices(kind):
        if n == name:
            return i
    return None


def _pick_rate(device: Optional[int], kind: str) -> int:
    if sd is None:
        return SAMPLE_RATE
    for rate in _CANDIDATE_RATES:
        try:
            if kind == "in":
                sd.check_input_settings(device=device, samplerate=rate,
                                        channels=1)
            else:
                sd.check_output_settings(device=device, samplerate=rate,
                                         channels=1)
            return rate
        except Exception:
            continue
    return 48000


def _resample(x: np.ndarray, fs_from: int, fs_to: int) -> np.ndarray:
    if fs_from == fs_to:
        return x
    if resample_poly is not None:
        g = np.gcd(fs_from, fs_to)
        return resample_poly(x, fs_to // g, fs_from // g)
    # crude linear fallback
    n = int(round(len(x) * fs_to / fs_from))
    xp = np.linspace(0, 1, len(x), endpoint=False)
    fp = np.linspace(0, 1, n, endpoint=False)
    return np.interp(fp, xp, x)


# --- capture -------------------------------------------------------------

class Capture:
    """Continuous input capture into a UTC-tagged ring buffer."""

    def __init__(self, device_name: str = "", gain: float = 1.0,
                 seconds: float = 135.0,
                 on_status: Optional[Callable[[str], None]] = None):
        self.device_name = device_name
        self.gain = gain
        self.on_status = on_status
        self._dev = _device_index(device_name, "in")
        self.fs = _pick_rate(self._dev, "in")
        self._cap = int(self.fs * seconds)
        self._buf = np.zeros(self._cap, dtype=np.float32)
        self._n = 0                    # total samples written (monotonic)
        self._t0: Optional[float] = None   # UTC of absolute sample 0
        self._lock = threading.Lock()
        self._stream = None
        self._level = 0.0

    # -- lifecycle --------------------------------------------------------

    def start(self, t0_utc: float) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is not available")
        self._t0 = t0_utc
        self._n = 0
        self._stream = sd.InputStream(
            samplerate=self.fs, channels=1, dtype="float32",
            device=self._dev, blocksize=0, callback=self._callback)
        self._stream.start()
        # Refine t0 using the stream's reported input latency.
        try:
            self._t0 = t0_utc - float(self._stream.latency)
        except Exception:
            pass
        if self.on_status:
            self.on_status(f"capture @ {self.fs} Hz")

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    @property
    def running(self) -> bool:
        return self._stream is not None

    # -- callback ---------------------------------------------------------

    def _callback(self, indata, frames, time_info, status):  # PortAudio thread
        block = indata[:, 0].astype(np.float32)
        if self.gain != 1.0:
            block = block * self.gain
        with self._lock:
            start = self._n % self._cap
            end = start + frames
            if end <= self._cap:
                self._buf[start:end] = block
            else:
                first = self._cap - start
                self._buf[start:] = block[:first]
                self._buf[:end - self._cap] = block[first:]
            self._n += frames
        if frames:
            self._level = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))

    # -- reads ------------------------------------------------------------

    def _read_abs(self, k0: int, k1: int) -> Optional[np.ndarray]:
        """Copy absolute sample range [k0, k1) if still buffered."""
        with self._lock:
            n = self._n
            if k0 < 0 or k1 > n or (n - k0) > self._cap:
                return None
            a = k0 % self._cap
            b = k1 % self._cap
            if a < b:
                return self._buf[a:b].copy()
            return np.concatenate((self._buf[a:], self._buf[:b]))

    def read_period(self, utc_start: float, seconds: float) -> Optional[np.ndarray]:
        """Return 12 kHz samples for the window starting at *utc_start*."""
        if self._t0 is None:
            return None
        k0 = int(round((utc_start - self._t0) * self.fs))
        k1 = k0 + int(round(seconds * self.fs))
        raw = self._read_abs(k0, k1)
        if raw is None:
            return None
        return _resample(raw, self.fs, SAMPLE_RATE)

    def latest(self, seconds: float) -> Optional[np.ndarray]:
        """Most recent *seconds* of raw capture (native rate), for the FFT."""
        n_samp = int(seconds * self.fs)
        with self._lock:
            n = self._n
            if n == 0:
                return None
            n_samp = min(n_samp, n, self._cap)
            k0 = n - n_samp
            a = k0 % self._cap
            b = n % self._cap
            if a < b:
                return self._buf[a:b].copy()
            return np.concatenate((self._buf[a:], self._buf[:b]))

    @property
    def level(self) -> float:
        return self._level


# --- transmit ------------------------------------------------------------

class TxPlayer:
    """Plays a rendered 12 kHz waveform out of the output device."""

    def __init__(self, device_name: str = "", level: float = 0.8):
        self.device_name = device_name
        self.level = level
        self._dev = _device_index(device_name, "out")
        self.fs = _pick_rate(self._dev, "out")
        self._stream = None
        self._data: Optional[np.ndarray] = None
        self._pos = 0
        self._on_done: Optional[Callable[[], None]] = None
        self._lock = threading.Lock()

    def play(self, samples_12k: np.ndarray, on_done: Optional[Callable[[], None]] = None) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is not available")
        self.stop()
        data = _resample(np.asarray(samples_12k, dtype=np.float32), SAMPLE_RATE, self.fs)
        data = np.clip(data * float(self.level), -1.0, 1.0).astype(np.float32)
        with self._lock:
            self._data = data
            self._pos = 0
            self._on_done = on_done
        self._stream = sd.OutputStream(
            samplerate=self.fs, channels=1, dtype="float32",
            device=self._dev, blocksize=0, callback=self._callback,
            finished_callback=self._finished)
        self._stream.start()

    def _callback(self, outdata, frames, time_info, status):  # PortAudio thread
        with self._lock:
            data, pos = self._data, self._pos
            if data is None or pos >= len(data):
                outdata.fill(0)
                raise sd.CallbackStop()
            end = min(pos + frames, len(data))
            chunk = data[pos:end]
            outdata[:len(chunk), 0] = chunk
            if len(chunk) < frames:
                outdata[len(chunk):, 0] = 0
            self._pos = end

    def _finished(self):
        cb = self._on_done
        if cb:
            cb()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    @property
    def playing(self) -> bool:
        return self._stream is not None and self._stream.active
