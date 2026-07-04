"""TCP client for rigctld, Hamlib's rig control daemon.

rigctld speaks a line-based text protocol: one command per line in,
one or more response lines out. "Set" commands are terminated by a
"RPRT <code>" status line; "get" commands reply with the requested
data instead (and only send RPRT on error). See Hamlib's netrigctl
backend for the reference implementation this client follows.
"""

from __future__ import annotations

import socket

# RPRT status codes, from Hamlib's rig.h (RIG_OK / RIG_E*).
_RIG_ERRORS = {
    0: "OK",
    -1: "invalid parameter",
    -2: "invalid configuration",
    -3: "memory shortage",
    -4: "function not implemented",
    -5: "communication timed out",
    -6: "IO error",
    -7: "internal Hamlib error",
    -8: "protocol error",
    -9: "command rejected by the rig",
    -10: "command performed, but arg truncated",
    -11: "function not available",
    -12: "VFO not targetable",
    -13: "bus error",
    -14: "bus is busy",
    -15: "invalid argument(s)",
    -16: "invalid VFO",
    -17: "argument out of domain of func",
    -18: "function deprecated",
    -19: "security error",
    -20: "rig not powered on",
    -21: "limit exceeded",
}


class RigctldError(Exception):
    """Raised when rigctld replies with a non-zero RPRT status."""

    def __init__(self, command: str, code: int) -> None:
        self.command = command
        self.code = code
        reason = _RIG_ERRORS.get(code, f"error {code}")
        super().__init__(f"{command!r} failed: {reason} (RPRT {code})")


class RigctlClient:
    """A minimal TCP client for rigctld.

    Usage:
        with RigctlClient("localhost", 4532) as rig:
            rig.set_freq(14_074_000)
            print(rig.get_mode())
    """

    def __init__(self, host: str = "localhost", port: int = 4532, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._rfile = None

    def connect(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._rfile = self._sock.makefile("r", newline="\n")
        # rigctld expects chk_vfo as the first command on a new connection;
        # some rig backends (e.g. dummy) hang on other commands otherwise.
        self._raw_command("\\chk_vfo")

    def close(self) -> None:
        if self._sock is None:
            return
        try:
            self._raw_command("q")
        except OSError:
            pass
        finally:
            self._rfile.close()
            self._sock.close()
            self._sock = None
            self._rfile = None

    def __enter__(self) -> "RigctlClient":
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- low-level protocol -------------------------------------------------

    def _readline(self) -> str:
        assert self._rfile is not None
        line = self._rfile.readline()
        if not line:
            raise ConnectionError("rigctld closed the connection")
        return line.rstrip("\r\n")

    def _raw_command(self, cmd: str) -> str:
        """Send a raw command line and return the first response line.

        Raises RigctldError if the response is a failing "RPRT <code>"
        status line. On success, returns "" for set commands (whose only
        reply is "RPRT 0") or the data line for get commands to parse.
        """
        if self._sock is None:
            raise RuntimeError("not connected; call connect() or use as a context manager")

        self._sock.sendall((cmd + "\n").encode("ascii"))
        line = self._readline()

        if line.startswith("RPRT"):
            code = int(line.split()[1])
            if code != 0:
                raise RigctldError(cmd, code)
            return ""

        return line

    @staticmethod
    def _vfo_suffix(vfo: str | None) -> str:
        return f" {vfo}" if vfo else ""

    # -- frequency -----------------------------------------------------------

    def get_freq(self, vfo: str | None = None) -> float:
        return float(self._raw_command(f"f{self._vfo_suffix(vfo)}"))

    def set_freq(self, freq: float, vfo: str | None = None) -> None:
        self._raw_command(f"F{self._vfo_suffix(vfo)} {freq:.0f}")

    # -- mode -----------------------------------------------------------------

    def get_mode(self, vfo: str | None = None) -> tuple[str, int]:
        mode = self._raw_command(f"m{self._vfo_suffix(vfo)}")
        width = int(self._readline())
        return mode, width

    def set_mode(self, mode: str, width: int = 0, vfo: str | None = None) -> None:
        self._raw_command(f"M{self._vfo_suffix(vfo)} {mode} {width}")

    # -- vfo --------------------------------------------------------------------

    def get_vfo(self) -> str:
        return self._raw_command("v")

    def set_vfo(self, vfo: str) -> None:
        self._raw_command(f"V {vfo}")

    # -- ptt / dcd -----------------------------------------------------------

    def get_ptt(self, vfo: str | None = None) -> bool:
        return bool(int(self._raw_command(f"t{self._vfo_suffix(vfo)}")))

    def set_ptt(self, ptt: bool, vfo: str | None = None) -> None:
        self._raw_command(f"T{self._vfo_suffix(vfo)} {int(ptt)}")

    def get_dcd(self, vfo: str | None = None) -> bool:
        return bool(int(self._raw_command(f"\\get_dcd{self._vfo_suffix(vfo)}")))

    # -- repeater shift / offset ----------------------------------------------

    def get_rptr_shift(self, vfo: str | None = None) -> str:
        return self._raw_command(f"r{self._vfo_suffix(vfo)}")

    def set_rptr_shift(self, shift: str, vfo: str | None = None) -> None:
        self._raw_command(f"R{self._vfo_suffix(vfo)} {shift}")

    def get_rptr_offs(self, vfo: str | None = None) -> int:
        return int(self._raw_command(f"o{self._vfo_suffix(vfo)}"))

    def set_rptr_offs(self, offset: int, vfo: str | None = None) -> None:
        self._raw_command(f"O{self._vfo_suffix(vfo)} {offset}")

    # -- CTCSS / DCS ------------------------------------------------------------

    def get_ctcss_tone(self, vfo: str | None = None) -> int:
        return int(self._raw_command(f"c{self._vfo_suffix(vfo)}"))

    def set_ctcss_tone(self, tone: int, vfo: str | None = None) -> None:
        self._raw_command(f"C{self._vfo_suffix(vfo)} {tone}")

    def get_dcs_code(self, vfo: str | None = None) -> int:
        return int(self._raw_command(f"d{self._vfo_suffix(vfo)}"))

    def set_dcs_code(self, code: int, vfo: str | None = None) -> None:
        self._raw_command(f"D{self._vfo_suffix(vfo)} {code}")

    # -- split ------------------------------------------------------------------

    def get_split_freq(self, vfo: str | None = None) -> float:
        return float(self._raw_command(f"i{self._vfo_suffix(vfo)}"))

    def set_split_freq(self, freq: float, vfo: str | None = None) -> None:
        self._raw_command(f"I{self._vfo_suffix(vfo)} {freq:.0f}")

    def get_split_mode(self, vfo: str | None = None) -> tuple[str, int]:
        mode = self._raw_command(f"x{self._vfo_suffix(vfo)}")
        width = int(self._readline())
        return mode, width

    def set_split_mode(self, mode: str, width: int = 0, vfo: str | None = None) -> None:
        self._raw_command(f"X{self._vfo_suffix(vfo)} {mode} {width}")

    def get_split_vfo(self, vfo: str | None = None) -> tuple[bool, str]:
        split = bool(int(self._raw_command(f"s{self._vfo_suffix(vfo)}")))
        tx_vfo = self._readline()
        return split, tx_vfo

    def set_split_vfo(self, split: bool, tx_vfo: str, vfo: str | None = None) -> None:
        self._raw_command(f"S{self._vfo_suffix(vfo)} {int(split)} {tx_vfo}")

    # -- RIT / XIT / tuning step --------------------------------------------

    def get_rit(self, vfo: str | None = None) -> int:
        return int(self._raw_command(f"j{self._vfo_suffix(vfo)}"))

    def set_rit(self, rit: int, vfo: str | None = None) -> None:
        self._raw_command(f"J{self._vfo_suffix(vfo)} {rit}")

    def get_xit(self, vfo: str | None = None) -> int:
        return int(self._raw_command(f"z{self._vfo_suffix(vfo)}"))

    def set_xit(self, xit: int, vfo: str | None = None) -> None:
        self._raw_command(f"Z{self._vfo_suffix(vfo)} {xit}")

    def get_ts(self, vfo: str | None = None) -> int:
        return int(self._raw_command(f"n{self._vfo_suffix(vfo)}"))

    def set_ts(self, ts: int, vfo: str | None = None) -> None:
        self._raw_command(f"N{self._vfo_suffix(vfo)} {ts}")

