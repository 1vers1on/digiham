"""WSJT-X UDP protocol output, so external tools can follow digiham.

This emits the same UDP datagrams WSJT-X broadcasts on its "UDP Server"
port, letting logging/mapping companions such as GridTracker, JTAlert or
the WSJT-X ``message_aggregator`` treat digiham as if it were WSJT-X. Only
the *outgoing* server messages are produced (Heartbeat, Status, Decode,
WSPR Decode, QSO Logged and Logged ADIF); incoming reply/control messages
are not acted upon.

The wire format is a big-endian ``QDataStream`` (Qt schema 3 / ``Qt_5_4``):
a magic number and schema, then the message type and a UTF-8 client id,
followed by the per-message fields. Field encodings mirror Qt's:

* ``bool``/``quint8``          one byte
* ``quint32``/``qint32``       four bytes, big-endian
* ``quint64``                  eight bytes, big-endian
* ``float``                    serialized as an IEEE-754 double (eight bytes)
* utf8 (``QByteArray``)        ``quint32`` length then the bytes; ``0xFFFFFFFF``
                               marks a null string
* ``QTime``                    ``quint32`` milliseconds since midnight
* ``QDateTime``                ``qint64`` Julian day, ``QTime``, and a
                               ``quint8`` time-spec (1 = UTC)

See WSJT-X's ``NetworkMessage.hpp`` for the authoritative description.
"""

from __future__ import annotations

import datetime as dt
import struct
from typing import Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QUdpSocket

from .adif import Qso, qso_to_adif
from .config import Config

_MAGIC = 0xADBCCBDA
_SCHEMA = 3                 # Qt_5_4 stream version
_MAX_SCHEMA = 3
_PULSE_S = 15               # NetworkMessage::pulse — heartbeat interval

# Message type ids (NetworkMessage::Type).
_HEARTBEAT = 0
_STATUS = 1
_DECODE = 2
_CLEAR = 3
_QSO_LOGGED = 5
_CLOSE = 6
_WSPR_DECODE = 10
_LOGGED_ADIF = 12

# proleptic-Gregorian ordinal (date(1,1,1) == 1) → Julian day number
_JULIAN_OFFSET = 1721425

# Single-character mode tag WSJT-X uses in Decode messages.
_MODE_CHAR = {"FT8": "~", "FT4": "+"}

_VERSION = "2.7.0"          # WSJT-X version we imitate for compatibility
_REVISION = "digiham"


def _msecs_of_day(ts: float) -> int:
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    return (d.hour * 3600 + d.minute * 60 + d.second) * 1000 + d.microsecond // 1000


class _Builder:
    """Assemble a single WSJT-X datagram in QDataStream (big-endian) form."""

    def __init__(self, msg_type: int, ident: str) -> None:
        self._b = bytearray()
        self.u32(_MAGIC)
        self.u32(_SCHEMA)
        self.u32(msg_type)
        self.utf8(ident)

    def bytes(self) -> bytes:
        return bytes(self._b)

    def u8(self, v: int) -> "_Builder":
        self._b += struct.pack(">B", v & 0xFF)
        return self

    def boolean(self, v: bool) -> "_Builder":
        self._b += struct.pack(">B", 1 if v else 0)
        return self

    def u32(self, v: int) -> "_Builder":
        self._b += struct.pack(">I", v & 0xFFFFFFFF)
        return self

    def i32(self, v: int) -> "_Builder":
        self._b += struct.pack(">i", int(v))
        return self

    def u64(self, v: int) -> "_Builder":
        self._b += struct.pack(">Q", v & 0xFFFFFFFFFFFFFFFF)
        return self

    def f64(self, v: float) -> "_Builder":
        self._b += struct.pack(">d", float(v))
        return self

    def utf8(self, s: Optional[str]) -> "_Builder":
        if s is None:
            return self.u32(0xFFFFFFFF)   # null QByteArray
        data = s.encode("utf-8")
        self.u32(len(data))
        self._b += data
        return self

    def qtime(self, msecs: int) -> "_Builder":
        return self.u32(msecs)

    def qdatetime(self, when: dt.datetime) -> "_Builder":
        when = when.astimezone(dt.timezone.utc)
        jdn = when.date().toordinal() + _JULIAN_OFFSET
        ms = ((when.hour * 3600 + when.minute * 60 + when.second) * 1000
              + when.microsecond // 1000)
        self._b += struct.pack(">q", jdn)     # QDate: Julian day number
        self.u32(ms)                          # QTime: ms since midnight
        return self.u8(1)                     # time-spec: 1 = UTC


class WsjtxReporter(QObject):
    """Broadcasts digiham's activity as WSJT-X UDP datagrams."""

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._sock = QUdpSocket(self)
        self._addr = QHostAddress()
        self._port = 0
        self._active = False
        self._hb = QTimer(self)
        self._hb.setInterval(_PULSE_S * 1000)
        self._hb.timeout.connect(self._heartbeat)

    @property
    def _ident(self) -> str:
        return self.cfg.udp_id or "digiham"

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self.apply_config(self.cfg)

    def apply_config(self, cfg: Config) -> None:
        was_active = self._active
        self.cfg = cfg
        if not cfg.udp_enabled:
            if was_active:
                self._send_close()
            self._active = False
            self._hb.stop()
            return
        self._addr = QHostAddress(cfg.udp_host or "127.0.0.1")
        self._port = int(cfg.udp_port or 2237)
        if self._addr.isMulticast():
            self._sock.setSocketOption(
                QAbstractSocket.SocketOption.MulticastTtlOption, 1)
        self._active = True
        if not self._hb.isActive():
            self._hb.start()
        self._heartbeat()      # announce ourselves immediately

    def stop(self) -> None:
        if self._active:
            self._send_close()
        self._active = False
        self._hb.stop()

    # -- outgoing messages ----------------------------------------------

    def _heartbeat(self) -> None:
        b = _Builder(_HEARTBEAT, self._ident)
        b.u32(_MAX_SCHEMA).utf8(_VERSION).utf8(_REVISION)
        self._emit(b)

    def _send_close(self) -> None:
        self._emit(_Builder(_CLOSE, self._ident), force=True)

    def report_status(self, st: dict) -> None:
        if not self._active:
            return
        b = _Builder(_STATUS, self._ident)
        b.u64(int(st.get("dial_hz", 0)))
        b.utf8(st.get("mode", ""))
        b.utf8(st.get("dx_call", ""))
        b.utf8(st.get("report", ""))
        b.utf8(st.get("tx_mode", st.get("mode", "")))
        b.boolean(st.get("tx_enabled", False))
        b.boolean(st.get("transmitting", False))
        b.boolean(st.get("decoding", False))
        b.u32(int(st.get("rx_df", 0)))
        b.u32(int(st.get("tx_df", 0)))
        b.utf8(st.get("de_call", ""))
        b.utf8(st.get("de_grid", ""))
        b.utf8(st.get("dx_grid", ""))
        b.boolean(st.get("watchdog", False))
        b.utf8(st.get("sub_mode", ""))
        b.boolean(st.get("fast_mode", False))
        b.u8(st.get("special_op_mode", 0))
        b.u32(0xFFFFFFFF)                          # frequency tolerance: n/a
        b.u32(int(st.get("tr_period", 15)))
        b.utf8(st.get("config_name", "digiham"))
        b.utf8(st.get("tx_message", ""))
        self._emit(b)

    def report_decode(self, row) -> None:
        """Send a Decode (FT8/FT4) or WSPR Decode message for one row."""
        if not self._active:
            return
        if row.mode == "WSPR":
            self._report_wspr(row)
            return
        b = _Builder(_DECODE, self._ident)
        b.boolean(True)                            # New
        b.qtime(_msecs_of_day(row.time_utc))
        b.i32(round(row.snr))
        b.f64(row.dt)
        b.u32(int(round(row.freq_audio)))
        b.utf8(_MODE_CHAR.get(row.mode, row.mode))
        b.utf8(row.message)
        b.boolean(False)                           # low confidence
        b.boolean(False)                           # off air
        self._emit(b)

    def _report_wspr(self, row) -> None:
        # WSPR message text is "CALL GRID PWR"; recover the power in dBm.
        power = 0
        parts = row.message.split()
        if parts:
            try:
                power = int(parts[-1])
            except ValueError:
                power = 0
        b = _Builder(_WSPR_DECODE, self._ident)
        b.boolean(True)                            # New
        b.qtime(_msecs_of_day(row.time_utc))
        b.i32(round(row.snr))
        b.f64(row.dt)
        b.u64(int(round(row.rf_hz)))               # absolute frequency, Hz
        b.i32(round(row.drift))
        b.utf8(row.de or (parts[0] if parts else ""))
        b.utf8(row.grid)
        b.i32(power)
        b.boolean(False)                           # off air
        self._emit(b)

    def report_qso(self, q: Qso) -> None:
        """Send QSO Logged and Logged ADIF messages for a completed QSO."""
        if not self._active:
            return
        t_on = _parse_dt(q.qso_date, q.time_on)
        t_off = _parse_dt(q.qso_date_off or q.qso_date, q.time_off or q.time_on)
        dial_hz = int(round(q.freq_mhz * 1e6))
        pwr = "" if q.tx_pwr_w is None else f"{q.tx_pwr_w:g}"

        b = _Builder(_QSO_LOGGED, self._ident)
        b.qdatetime(t_off)
        b.utf8(q.call)
        b.utf8(q.gridsquare)
        b.u64(dial_hz)
        b.utf8(q.mode)
        b.utf8(q.rst_sent)
        b.utf8(q.rst_rcvd)
        b.utf8(pwr)
        b.utf8(q.comment)
        b.utf8("")                                 # name
        b.qdatetime(t_on)
        b.utf8(q.station_callsign)                 # operator call
        b.utf8(q.station_callsign)                 # my call
        b.utf8(q.my_gridsquare)
        b.utf8("")                                 # exchange sent
        b.utf8("")                                 # exchange received
        b.utf8("")                                 # ADIF propagation mode
        self._emit(b)

        adif = ("\n<adif_ver:5>3.1.0\n"
                f"<programid:{len(self._ident)}>{self._ident}\n<EOH>\n"
                + qso_to_adif(q))
        self._emit(_Builder(_LOGGED_ADIF, self._ident).utf8(adif))

    # -- transport -------------------------------------------------------

    def _emit(self, b: _Builder, force: bool = False) -> None:
        if not (self._active or force) or self._port == 0 or self._addr.isNull():
            return
        try:
            self._sock.writeDatagram(b.bytes(), self._addr, self._port)
        except Exception:
            pass


def _parse_dt(date_str: str, time_str: str) -> dt.datetime:
    """Parse ADIF YYYYMMDD / HHMMSS(UTC) strings into an aware datetime."""
    try:
        naive = dt.datetime.strptime(
            date_str + time_str.ljust(6, "0")[:6], "%Y%m%d%H%M%S")
        return naive.replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        return dt.datetime.now(dt.timezone.utc)
