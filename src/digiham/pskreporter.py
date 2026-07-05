"""Spot reporting to PSK Reporter (https://pskreporter.info).

PSK Reporter collects reception reports from digital-mode stations and maps
who is hearing whom. Reports are submitted as IPFIX (RFC 7011) records over
UDP to ``report.pskreporter.info:4739`` — the same wire format WSJT-X uses.

An IPFIX message is a 16-byte header followed by a series of *sets*. Two
kinds carry our data:

* a *receiver* record — who we are (call, grid, decoding software, antenna),
  described by an options template (set id 3, template ``0x9992``);
* a batch of *sender* records — the stations we decoded (call, RF frequency,
  SNR, mode, grid, and the time we heard them), described by a plain template
  (set id 2, template ``0x9993``).

Most fields are PSK Reporter's own IPFIX elements under enterprise number
30351 (``0x768F``); the spot time is the standard ``flowStartSeconds``
element 150. Because UDP is stateless, the templates are re-sent with every
report so a restarted collector can always interpret the data that follows.

Spots are queued as they decode and flushed in a batch every few minutes (PSK
Reporter asks senders not to report more often than that). A per-call cache
suppresses repeats of the same station within the flush window to keep our
load on the collector down, mirroring WSJT-X's behaviour.
"""

from __future__ import annotations

import logging
import random
import struct
import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QAbstractSocket, QUdpSocket

from . import sequencer as seq
from .config import Config

logger = logging.getLogger(__name__)

HOST = "report.pskreporter.info"
PORT = 4739

# PSK Reporter asks senders to report no more often than every 5 minutes.
SEND_INTERVAL_S = 180
# Suppress a repeat spot of the same call heard again within this window.
CACHE_TIMEOUT_S = 180
# Cap the pending queue so a long outage can't grow it without bound.
MAX_PENDING = 2048
# Keep each datagram comfortably under a typical MTU to avoid fragmentation.
MAX_PAYLOAD = 1400

_ENTERPRISE = b"\x00\x00\x76\x8f"          # 30351, PSK Reporter's IANA PEN
_RX_TEMPLATE_ID = 0x9992
_TX_TEMPLATE_ID = 0x9993
_INFO_SOURCE_AUTO = 1                       # spot came from an automatic decoder

# Receiver options-template descriptor (set id 3): receiverCallsign (0x8002),
# receiverLocator (0x8004), decoderSoftware (0x8008), antennaInformation
# (0x8009). 4-byte trailer pads the set to a 4-byte boundary.
_RX_DESCRIPTOR = bytes.fromhex(
    "0003002c" "99920004" "0000"
    "8002ffff" "0000768f"
    "8004ffff" "0000768f"
    "8008ffff" "0000768f"
    "8009ffff" "0000768f"
    "0000")

# Sender template descriptor (set id 2): senderCallsign (0x8001),
# frequency (0x8005, u32), sNR (0x8006, s8), mode (0x800a),
# senderLocator (0x8003), informationSource (0x800b, u8) and the standard
# flowStartSeconds element (150, u32).
_TX_DESCRIPTOR = bytes.fromhex(
    "0002003c" "99930007"
    "8001ffff" "0000768f"
    "80050004" "0000768f"
    "80060001" "0000768f"
    "800affff" "0000768f"
    "8003ffff" "0000768f"
    "800b0001" "0000768f"
    "00960004")


@dataclass(frozen=True)
class Spot:
    call: str
    grid: str
    freq_hz: int
    mode: str
    snr: int
    epoch: int          # UTC seconds we heard the station


@dataclass(frozen=True)
class Receiver:
    call: str
    grid: str
    software: str
    antenna: str = ""


def _vstr(s: str) -> bytes:
    """IPFIX variable-length string: a one-byte length then UTF-8 bytes.

    PSK Reporter limits each field to a 254-byte short form, which is far more
    than any callsign, grid or software string needs.
    """
    data = (s or "").encode("utf-8", "replace")[:254]
    return bytes((len(data),)) + data


def _set(set_id: int, body: bytes) -> bytes:
    """Wrap a record body in an IPFIX set header, padded to 4 bytes."""
    length = 4 + len(body)
    body += b"\x00" * (-length % 4)
    return struct.pack(">HH", set_id, 4 + len(body)) + body


def _receiver_record(rx: Receiver) -> bytes:
    return _vstr(rx.call) + _vstr(rx.grid) + _vstr(rx.software) + _vstr(rx.antenna)


def _sender_record(sp: Spot) -> bytes:
    snr = max(-128, min(127, int(sp.snr)))
    return (_vstr(sp.call)
            + struct.pack(">I", sp.freq_hz & 0xFFFFFFFF)
            + struct.pack(">b", snr)
            + _vstr(sp.mode)
            + _vstr(sp.grid)
            + struct.pack(">B", _INFO_SOURCE_AUTO)
            + struct.pack(">I", sp.epoch & 0xFFFFFFFF))


def build_packets(rx: Receiver, spots: list[Spot], seq_number: int,
                  observation_id: int) -> tuple[list[bytes], int]:
    """Build IPFIX datagrams carrying ``spots``, splitting on ``MAX_PAYLOAD``.

    Every datagram re-sends the templates (UDP is stateless) and repeats the
    receiver record, then packs as many sender records as fit. Returns the
    datagrams and the next sequence number (advanced by one per sender record,
    per RFC 7011).
    """
    packets: list[bytes] = []
    rx_set = _set(_RX_TEMPLATE_ID, _receiver_record(rx))
    # Fixed overhead before the sender set: header + both templates + rx set +
    # the sender set's own 4-byte header.
    overhead = 16 + len(_RX_DESCRIPTOR) + len(_TX_DESCRIPTOR) + len(rx_set) + 4
    i, n = 0, len(spots)
    while i < n:
        body = b""
        count = 0
        while i < n:
            rec = _sender_record(spots[i])
            if count and overhead + len(body) + len(rec) > MAX_PAYLOAD:
                break
            body += rec
            count += 1
            i += 1
        payload = (_RX_DESCRIPTOR + _TX_DESCRIPTOR + rx_set
                   + _set(_TX_TEMPLATE_ID, body))
        export_time = int(time.time())
        header = struct.pack(">HHIII", 0x000A, 16 + len(payload),
                             export_time, seq_number, observation_id)
        packets.append(header + payload)
        seq_number = (seq_number + count) & 0xFFFFFFFF
    return packets, seq_number


class PskReporter(QObject):
    """Queues decodes and flushes them to PSK Reporter as IPFIX over UDP."""

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._sock = QUdpSocket(self)
        self._active = False
        self._spots: list[Spot] = []
        self._cache: dict[str, float] = {}      # base call -> last-spotted epoch
        self._seq = 0
        # A constant-per-session id lets the collector group our datagrams
        # even as our source UDP port changes behind NAT.
        self._obs_id = random.getrandbits(32)
        self._timer = QTimer(self)
        self._timer.setInterval(SEND_INTERVAL_S * 1000)
        self._timer.timeout.connect(self._flush)

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self.apply_config(self.cfg)

    def apply_config(self, cfg: Config) -> None:
        self.cfg = cfg
        active = bool(cfg.pskreporter and cfg.my_call)
        if active and not self._active:
            logger.info("pskreporter enabled for %s", cfg.my_call)
        elif not active and self._active:
            logger.info("pskreporter disabled")
            self._spots.clear()
        self._active = active
        if active:
            self._ensure_socket()
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def stop(self) -> None:
        if self._active and self._spots:
            self._flush()
        self._active = False
        self._timer.stop()
        if self._sock.state() != QAbstractSocket.SocketState.UnconnectedState:
            self._sock.disconnectFromHost()

    # -- spot intake -----------------------------------------------------

    def report_decode(self, row) -> None:
        """Queue one decoded station for the next report, if it's spottable."""
        if not self._active:
            return
        call = row.de
        if not call or (self.cfg.my_call and seq.same_call(call, self.cfg.my_call)):
            return
        now = time.time()
        # De-dupe repeats within the flush window, but always let VHF+ and any
        # spot of a call we've not seen this window through.
        last = self._cache.get(call)
        if last is not None and row.rf_hz <= 49_000_000 \
                and now - last < CACHE_TIMEOUT_S:
            return
        self._cache[call] = now
        self._spots.append(Spot(
            call=call, grid=row.grid or "", freq_hz=int(round(row.rf_hz)),
            mode=row.mode, snr=int(round(row.snr)), epoch=int(row.time_utc)))
        if len(self._spots) > MAX_PENDING:
            del self._spots[:-MAX_PENDING]
        self._prune_cache(now)

    def _prune_cache(self, now: float) -> None:
        stale = [c for c, t in self._cache.items() if now - t > CACHE_TIMEOUT_S * 2]
        for c in stale:
            del self._cache[c]

    # -- transport -------------------------------------------------------

    def _ensure_socket(self) -> None:
        st = self._sock.state()
        if st in (QAbstractSocket.SocketState.UnconnectedState,):
            # connectToHost resolves the name and sets a default peer so we can
            # use write() for these pseudo-connected UDP datagrams.
            self._sock.connectToHost(HOST, PORT,
                                     QAbstractSocket.OpenModeFlag.WriteOnly)

    def _flush(self) -> None:
        if not self._spots:
            return
        if self._sock.state() != QAbstractSocket.SocketState.ConnectedState:
            # Not connected yet (or dropped): keep the spots and try to (re)open
            # so the next flush can send them.
            self._ensure_socket()
            return
        rx = Receiver(self.cfg.my_call, self.cfg.my_grid,
                      f"digiham {_version()}", "")
        spots, self._spots = self._spots, []
        try:
            packets, self._seq = build_packets(rx, spots, self._seq, self._obs_id)
            for payload in packets:
                self._sock.write(payload)
            logger.info("pskreporter: sent %d spot(s) in %d packet(s)",
                        len(spots), len(packets))
        except Exception:
            logger.exception("pskreporter: failed to send report")


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("digiham")
    except Exception:
        return "0.1"
