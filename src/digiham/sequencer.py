"""FT8/FT4 message parsing and the QSO auto-sequencer.

This module has no GUI or I/O dependencies: it turns decoded message text
into structured :class:`ParsedMessage` values, generates the six standard
WSJT-X transmit messages, and runs the state machine that advances a QSO
automatically (the "Auto Seq" behaviour).

The exchange it drives is the ordinary FT8 QSO::

    CQ K1ABC FN42                 <- Tx6 (call CQ)
        K1ABC W9XYZ EM73          <- Tx1 (answer, with grid)
    W9XYZ K1ABC -19               <- Tx2 (signal report)
        K1ABC W9XYZ R-15          <- Tx3 (roger + report)
    W9XYZ K1ABC RR73              <- Tx4 (rogers)
        K1ABC W9XYZ 73            <- Tx5 (sign off)

The sequencer keys its transitions on the *kind* of message received from
the current DX station, which sequences identically whether we are the
station calling CQ or the station answering one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# --- callsign / grid / report primitives --------------------------------

_GRID4 = re.compile(r"^[A-R]{2}[0-9]{2}$")
_GRID6 = re.compile(r"^[A-R]{2}[0-9]{2}[A-X]{2}$")
_REPORT = re.compile(r"^R?[+-][0-9]{2}$")
_CALL = re.compile(r"^[A-Z0-9/]{3,}$")


def is_grid(tok: str) -> bool:
    return bool(_GRID4.match(tok) or _GRID6.match(tok))


def is_report(tok: str) -> bool:
    return bool(_REPORT.match(tok))


def is_call(tok: str) -> bool:
    """Loose test for something that looks like a callsign token."""
    if tok in ("CQ", "DE", "QRZ", "RR73", "RRR", "73"):
        return False
    if not _CALL.match(tok):
        return False
    return any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)


def base_call(call: str) -> str:
    """Strip a ``/P`` ``/R`` ``/QRP`` style suffix and any prefix."""
    call = call.strip("<>").upper()
    if "/" in call:
        parts = call.split("/")
        # Keep the longest part; that is normally the real call.
        parts.sort(key=len, reverse=True)
        return parts[0]
    return call


def same_call(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return base_call(a) == base_call(b)


def fmt_report(n: int) -> str:
    """Format a signal report the WSJT-X way: ``-05``, ``+00``, ``-19``."""
    n = max(-30, min(49, int(round(n))))
    return f"{n:+03d}"


def parse_report(tok: str) -> Optional[int]:
    m = _REPORT.match(tok)
    if not m:
        return None
    return int(tok.lstrip("R"))


# --- parsed message -----------------------------------------------------

# Message "kinds" that drive the sequencer, roughly in exchange order.
K_CQ = "CQ"
K_GRID = "GRID"
K_REPORT = "REPORT"
K_RREPORT = "RREPORT"
K_RRR = "RRR"
K_RR73 = "RR73"
K_73 = "73"
K_FREE = "FREE"


@dataclass
class ParsedMessage:
    raw: str
    to: str = ""            # addressee callsign, or "CQ"
    de: str = ""            # sender callsign ("" if unknown)
    is_cq: bool = False
    cq_dir: str = ""        # directional CQ target, e.g. "DX", "EU", "POTA"
    grid: str = ""
    report: Optional[int] = None
    kind: str = K_FREE

    @property
    def addressed_to_me_key(self) -> str:
        return base_call(self.to)


def parse(raw: str) -> ParsedMessage:
    """Parse a decoded FT8/FT4 message into a :class:`ParsedMessage`."""
    text = " ".join(raw.upper().split())
    toks = text.split()
    pm = ParsedMessage(raw=raw)
    if not toks:
        return pm

    if toks[0] == "CQ":
        pm.is_cq = True
        pm.to = "CQ"
        pm.kind = K_CQ
        rest = toks[1:]
        # Optional directional target: "CQ DX K1ABC FN42", "CQ POTA ..."
        if rest and not is_call(rest[0]) and not is_grid(rest[0]):
            pm.cq_dir = rest[0]
            rest = rest[1:]
        if rest and is_call(rest[0]):
            pm.de = rest[0]
            rest = rest[1:]
        if rest and is_grid(rest[0]):
            pm.grid = rest[0]
        return pm

    # Directed message: "<to> <de> [field]"
    pm.to = toks[0]
    if len(toks) >= 2:
        pm.de = toks[1]
    field = toks[2] if len(toks) >= 3 else ""

    if field == "RR73":
        pm.kind = K_RR73
    elif field == "RRR":
        pm.kind = K_RRR
    elif field == "73":
        pm.kind = K_73
    elif is_report(field):
        pm.report = parse_report(field)
        pm.kind = K_RREPORT if field.startswith("R") else K_REPORT
    elif is_grid(field):
        pm.grid = field
        pm.kind = K_GRID
    elif not field and is_call(pm.to) and is_call(pm.de):
        # "<to> <de>" with no field is still a call/answer.
        pm.kind = K_GRID
    else:
        pm.kind = K_FREE
    return pm


# --- standard message generation ----------------------------------------

def standard_messages(mycall: str, mygrid: str, dxcall: str,
                      report_out: int, use_rr73: bool = True) -> list[str]:
    """The six WSJT-X standard messages for a QSO with *dxcall*.

    ``report_out`` is the report we send DX (how we hear them).
    """
    mycall = mycall.upper().strip()
    dxcall = dxcall.upper().strip()
    grid = mygrid.upper().strip()[:4]
    g = f" {grid}" if grid else ""
    r = fmt_report(report_out)
    rrr = "RR73" if use_rr73 else "RRR"
    return [
        f"{dxcall} {mycall}{g}".strip(),        # Tx1: answer with grid
        f"{dxcall} {mycall} {r}",                # Tx2: report
        f"{dxcall} {mycall} R{r}",               # Tx3: roger + report
        f"{dxcall} {mycall} {rrr}",              # Tx4: rogers
        f"{dxcall} {mycall} 73",                 # Tx5: sign off
        f"CQ {mycall}{g}".strip(),               # Tx6: call CQ
    ]


# --- sequencer state machine --------------------------------------------

@dataclass
class LogRequest:
    """Emitted when the sequencer decides a QSO should be logged."""
    dxcall: str
    dxgrid: str
    report_sent: int
    report_recv: Optional[int]


@dataclass
class Sequencer:
    mycall: str = ""
    mygrid: str = ""
    use_rr73: bool = True

    # live QSO state
    dxcall: str = ""
    dxgrid: str = ""
    report_out: int = 0             # what we send DX
    report_in: Optional[int] = None  # what DX sent us
    calling_cq: bool = True          # True when we are the CQ station
    in_qso: bool = False
    logged: bool = False
    next_tx: int = 6                 # 1..6, which Tx message is queued next
    messages: list[str] = field(default_factory=lambda: [""] * 6)

    def __post_init__(self) -> None:
        self._regen()

    # -- message upkeep ---------------------------------------------------

    def _regen(self) -> None:
        dx = self.dxcall or "DX"
        self.messages = standard_messages(
            self.mycall or "MYCALL", self.mygrid, dx, self.report_out,
            self.use_rr73)

    def set_station(self, mycall: str, mygrid: str) -> None:
        self.mycall, self.mygrid = mycall.upper(), mygrid.upper()
        self._regen()

    def current_message(self) -> str:
        idx = max(1, min(6, self.next_tx))
        return self.messages[idx - 1]

    def select_tx(self, idx: int) -> None:
        self.next_tx = max(1, min(6, idx))

    # -- QSO lifecycle ----------------------------------------------------

    def start_cq(self) -> None:
        self.in_qso = False
        self.calling_cq = True
        self.dxcall = ""
        self.dxgrid = ""
        self.report_in = None
        self.logged = False
        self.next_tx = 6
        self._regen()

    def answer_cq(self, dxcall: str, dxgrid: str, report_out: int) -> None:
        """Begin answering a station that was calling CQ (we are the caller)."""
        self._begin(dxcall, dxgrid, report_out, calling_cq=False)
        self.next_tx = 1

    def answer_caller(self, dxcall: str, dxgrid: str, report_out: int) -> None:
        """Begin responding to a station that answered our CQ."""
        self._begin(dxcall, dxgrid, report_out, calling_cq=True)
        self.next_tx = 2

    def _begin(self, dxcall: str, dxgrid: str, report_out: int,
               calling_cq: bool) -> None:
        self.in_qso = True
        self.calling_cq = calling_cq
        self.dxcall = base_call(dxcall)
        self.dxgrid = dxgrid
        self.report_out = int(round(report_out))
        self.report_in = None
        self.logged = False
        self._regen()

    def halt(self) -> None:
        self.in_qso = False
        self.start_cq()

    def is_for_me(self, pm: ParsedMessage) -> bool:
        return bool(self.mycall) and same_call(pm.to, self.mycall)

    def is_current_dx(self, pm: ParsedMessage) -> bool:
        return self.in_qso and same_call(pm.de, self.dxcall)

    # -- reactive transitions --------------------------------------------

    def on_decode(self, pm: ParsedMessage, snr: float) -> Optional[LogRequest]:
        """Advance the *current* QSO given a message from our DX to us.

        This only fires when we are already working the station the message
        came from; use :meth:`engage` to pick a station up from a cold start.
        Returns a :class:`LogRequest` when the exchange reaches a point that
        should be logged, otherwise ``None``.
        """
        if not (self.in_qso and self.is_for_me(pm) and self.is_current_dx(pm)):
            return None
        return self._advance(pm, snr)

    def engage(self, pm: ParsedMessage, snr: float) -> Optional[LogRequest]:
        """Start or continue a QSO in reply to a message addressed to us.

        Unlike :meth:`on_decode` this works from any state: when we are not
        already working the sender it infers our role (were we the CQ
        station, or did we answer a CQ?) from the kind of message, sets the
        QSO up, then advances to the correct reply. This is the single entry
        point for both manual pick-up (double-click) and auto-sequencing a
        fresh caller, so the two always choose the same message.
        """
        dxcall = base_call(pm.de)
        if not dxcall or same_call(dxcall, self.mycall):
            return None
        if not (self.in_qso and same_call(dxcall, self.dxcall)):
            calling_cq = self._role_for_kind(pm.kind)
            self._begin(dxcall, pm.grid, snr, calling_cq)
            # A sane starting reply before the message-specific advance: the
            # CQ station answers a caller with a report (Tx2); a caller
            # answers a CQ with its grid (Tx1).
            self.next_tx = 2 if calling_cq else 1
        return self._advance(pm, snr)

    def _role_for_kind(self, kind: str) -> bool:
        """Infer whether *we* were the CQ station for a fresh engagement.

        The message DX just sent us pins down who called whom: a grid (or a
        bare answer) or an ``R`` report means DX answered *our* CQ, so we are
        the CQ station; a plain report or a roger means DX called CQ and we
        answered it.
        """
        if kind in (K_GRID, K_RREPORT):
            return True
        if kind in (K_REPORT, K_RRR, K_RR73, K_73):
            return False
        return self.calling_cq

    def _advance(self, pm: ParsedMessage, snr: float) -> Optional[LogRequest]:
        """Move the state machine one step for a message from our DX.

        Assumes the QSO is set up and *pm* is addressed to us by the current
        DX; :meth:`on_decode` and :meth:`engage` enforce that.
        """
        log: Optional[LogRequest] = None
        if pm.kind == K_GRID:
            if pm.grid:
                self.dxgrid = pm.grid
            # Only the CQ station steps forward on a bare grid/answer; a
            # caller has already sent its grid and is waiting for a report,
            # so it simply holds and lets its current message repeat.
            if self.calling_cq:
                self.next_tx = 2
        elif pm.kind == K_REPORT:
            self.report_in = pm.report
            self.next_tx = 3
        elif pm.kind == K_RREPORT:
            self.report_in = pm.report
            self.next_tx = 4
        elif pm.kind in (K_RRR, K_RR73):
            self.next_tx = 5
            log = self._log_request()
        elif pm.kind == K_73:
            self.next_tx = 6
            log = self._log_request()
        self._regen()
        return log

    def on_transmitted(self, idx: int) -> Optional[LogRequest]:
        """Called after a message was sent; may trigger a log / QSO end."""
        log: Optional[LogRequest] = None
        if idx == 4:                       # we (CQ station) sent RR73
            log = self._log_request()
            # QSO complete from our side; drop back to calling CQ.
            self.in_qso = False
            self.calling_cq = True
            self.next_tx = 6
        elif idx == 5:                     # we sent 73
            self.in_qso = False
            self.calling_cq = True
            self.next_tx = 6
        self._regen()
        return log

    def _log_request(self) -> Optional[LogRequest]:
        if self.logged or not self.dxcall:
            return None
        self.logged = True
        return LogRequest(self.dxcall, self.dxgrid, self.report_out,
                          self.report_in)
