"""TCP client for rigctld, Hamlib's rig control daemon.

rigctld speaks a line-based text protocol: one command per line in,
one or more response lines out. "Set" commands are terminated by a
"RPRT <code>" status line; "get" commands reply with the requested
data instead (and only send RPRT on error). See Hamlib's netrigctl
backend for the reference implementation this client follows.

Two hard-won lessons are baked in here:

* Mode names must be validated before they are sent. rigctld parses an
  unknown mode string as RIG_MODE_NONE and *still returns RPRT 0*, and
  some backends then switch the rig to an arbitrary mode (an FTDX-10
  was observed dropping into FM after ``M DATA-U 0``).

* After a read timeout the reply eventually lands in the socket buffer
  and every later response would be off by one forever. Like Hamlib's
  own netrigctl (``rig_flush``), the input buffer is drained before the
  next command whenever the stream may be dirty.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

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

# Mode names rigctld's rig_parse_mode() understands (rig.c).
HAMLIB_MODES = frozenset({
    "USB", "LSB", "CW", "CWR", "CWN", "RTTY", "RTTYR",
    "AM", "AMN", "AMS", "FM", "FMN", "WFM",
    "PKTUSB", "PKTLSB", "PKTFM", "PKTFMN", "PKTAM",
    "ECSSUSB", "ECSSLSB", "SAM", "SAL", "SAH", "DSB",
    "PSK", "PSKR", "DD", "C4FM", "DSTAR",
})

# Radio-front-panel spellings -> Hamlib names.
MODE_ALIASES = {
    "DATA-U": "PKTUSB", "DATA-L": "PKTLSB", "DATA-FM": "PKTFM",
    "DATA-USB": "PKTUSB", "DATA-LSB": "PKTLSB", "DATA": "PKTUSB",
    "DIGU": "PKTUSB", "DIGL": "PKTLSB",
}


def normalize_mode(mode: str) -> str:
    """Map *mode* to the Hamlib name, or raise ValueError if unknown.

    "" passes through (meaning "leave the rig's mode alone").
    """
    m = mode.strip().upper()
    m = MODE_ALIASES.get(m, m)
    if m and m not in HAMLIB_MODES:
        raise ValueError(
            f"unknown rig mode {mode!r} (use a Hamlib name, e.g. PKTUSB for DATA-U)")
    return m


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
        self.vfo_mode = False       # rigctld running with --vfo?
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._dirty = False         # a timeout may have left unread reply lines

    def connect(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._buf.clear()
        self._dirty = False
        # rigctld expects chk_vfo as the first command on a new connection;
        # some rig backends (e.g. dummy) hang on other commands otherwise.
        # Reply is "CHKVFO <n>" or bare "<n>"; n=1 means rigctld runs in
        # --vfo mode and every command must carry a VFO argument.
        reply = self._raw_command("\\chk_vfo")
        self.vfo_mode = reply.split()[-1] == "1" if reply else False

    def close(self) -> None:
        if self._sock is None:
            return
        try:
            self._raw_command("q")
        except OSError:
            pass
        finally:
            self._sock.close()
            self._sock = None
            self._buf.clear()

    def __enter__(self) -> "RigctlClient":
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- low-level protocol -------------------------------------------------

    def _readline(self) -> str:
        assert self._sock is not None
        while b"\n" not in self._buf:
            try:
                data = self._sock.recv(4096)
            except TimeoutError:
                # the reply may still arrive later; flush before next command
                self._dirty = True
                raise
            if not data:
                raise ConnectionError("rigctld closed the connection")
            self._buf += data
        line, _, rest = bytes(self._buf).partition(b"\n")
        self._buf = bytearray(rest)
        return line.decode("ascii", "replace").rstrip("\r")

    def _flush_input(self) -> None:
        """Drop any stale reply lines left over from a timed-out command."""
        assert self._sock is not None
        self._buf.clear()
        self._sock.setblocking(False)
        try:
            while True:
                if not self._sock.recv(4096):
                    raise ConnectionError("rigctld closed the connection")
        except BlockingIOError:
            pass
        finally:
            self._sock.settimeout(self.timeout)
        self._dirty = False

    def _raw_command(self, cmd: str) -> str:
        """Send a raw command line and return the first response line.

        Raises RigctldError if the response is a failing "RPRT <code>"
        status line. On success, returns "" for set commands (whose only
        reply is "RPRT 0") or the data line for get commands to parse.
        """
        if self._sock is None:
            raise RuntimeError("not connected; call connect() or use as a context manager")

        if self._dirty:
            self._flush_input()
        self._sock.sendall((cmd + "\n").encode("ascii"))
        line = self._readline()

        if line.startswith("RPRT"):
            code = int(line.split()[1])
            if code != 0:
                raise RigctldError(cmd, code)
            return ""

        return line

    def _vfo_suffix(self, vfo: str | None) -> str:
        if vfo:
            return f" {vfo}"
        # in --vfo mode every command needs a VFO; currVFO keeps behaviour
        # identical to non-vfo mode
        return " currVFO" if self.vfo_mode else ""

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
        mode = normalize_mode(mode)
        if not mode:
            return
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

    # -- levels / functions ----------------------------------------------------

    def get_level(self, name: str, vfo: str | None = None) -> float:
        """Read a level (meter) by Hamlib name, e.g. SWR, STRENGTH, ALC,
        RFPOWER_METER_WATTS, VD_METER."""
        return float(self._raw_command(f"l{self._vfo_suffix(vfo)} {name}"))

    def set_level(self, name: str, value: float, vfo: str | None = None) -> None:
        self._raw_command(f"L{self._vfo_suffix(vfo)} {name} {value:g}")

    def get_func(self, name: str, vfo: str | None = None) -> bool:
        return bool(int(self._raw_command(f"u{self._vfo_suffix(vfo)} {name}")))

    def set_func(self, name: str, status: bool, vfo: str | None = None) -> None:
        self._raw_command(f"U{self._vfo_suffix(vfo)} {name} {int(status)}")

    # -- power ------------------------------------------------------------------

    def get_powerstat(self) -> bool:
        return bool(int(self._raw_command("\\get_powerstat")))

    def set_powerstat(self, on: bool) -> None:
        self._raw_command(f"\\set_powerstat {int(on)}")

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
        mode = normalize_mode(mode)
        if not mode:
            return
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


# ---------------------------------------------------------------------------
# Managed rigctld: launch and supervise a private daemon.
#
# digiham can either talk to a rigctld the user started themselves (the
# "external" case) or run its own. The pieces below implement the latter:
# locate the rigctld binary across platforms, pick a loopback port nothing
# else is using, start the daemon, wait for it to listen, and shut it down.
# ---------------------------------------------------------------------------

RIGCTLD_EXE = "rigctld.exe" if sys.platform == "win32" else "rigctld"


class RigctldStartError(Exception):
    """Raised when a managed rigctld process cannot be started."""


def _bundled_hamlib_dir() -> Path | None:
    """Directory of the rigctld we ship with digiham, or ``None``.

    Two layouts are recognised, mirroring the staging in
    ``packaging/build-hamlib.sh`` (``<root>/bin/rigctld``, ``<root>/lib/*``):

    * **Frozen app** (PyInstaller): the spec drops the tree under ``hamlib/``
      inside the bundle, next to which :data:`sys._MEIPASS` points.
    * **Running from source**: the same ``packaging/hamlib`` staging dir, so a
      developer who has run ``build-hamlib.sh`` gets the bundled binary too.
    """
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass) / "hamlib")
    else:
        # <repo>/src/digiham/rigctl.py -> <repo>/packaging/hamlib
        roots.append(Path(__file__).resolve().parents[2] / "packaging" / "hamlib")
    for root in roots:
        if (root / "bin" / RIGCTLD_EXE).is_file():
            return root
    return None


def _bundled_rigctld() -> str | None:
    """Path to the bundled rigctld binary if one shipped, else ``None``."""
    root = _bundled_hamlib_dir()
    if root is None:
        return None
    exe = root / "bin" / RIGCTLD_EXE
    return str(exe) if os.access(exe, os.X_OK) else None


def _extra_search_dirs() -> list[Path]:
    """Platform-specific directories to search beyond ``PATH``.

    Hamlib's installer and the common package managers drop rigctld in a
    handful of predictable places that are not always on a GUI app's
    inherited ``PATH`` (especially on macOS and Windows).
    """
    if sys.platform == "win32":
        dirs: list[Path] = []
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env)
            if base:
                # Hamlib's Windows build unpacks to <name>-<ver>\bin
                dirs.append(Path(base) / "hamlib" / "bin")
                dirs.append(Path(base) / "Hamlib" / "bin")
        return dirs
    if sys.platform == "darwin":
        return [
            Path("/opt/homebrew/bin"),   # Homebrew on Apple silicon
            Path("/usr/local/bin"),      # Homebrew on Intel / manual builds
            Path("/opt/local/bin"),      # MacPorts
        ]
    # Linux, *BSD and anything else.
    return [
        Path("/usr/bin"), Path("/usr/local/bin"), Path("/bin"),
        Path("/usr/sbin"), Path("/usr/local/sbin"),
    ]


def find_rigctld(explicit: str = "") -> str:
    """Locate the rigctld executable and return its path.

    Search order:

    1. *explicit* — a user-supplied path (Settings → rigctld binary). An
       explicit choice always wins so the user can override everything else.
       It may point at the binary itself or at the directory containing it.
    2. The **bundled** rigctld shipped inside digiham (the internal Hamlib).
    3. ``PATH`` via :func:`shutil.which` (an **external**, system Hamlib).
    4. A handful of platform-specific install locations
       (see :func:`_extra_search_dirs`).

    Raises :class:`FileNotFoundError` if nothing is found.
    """
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            p = p / RIGCTLD_EXE
        found = shutil.which(str(p))   # honours PATHEXT on Windows, checks +x
        if found:
            return found
        raise FileNotFoundError(f"rigctld not found at {explicit!r}")

    # Prefer the internal (bundled) Hamlib; fall back to an external one.
    bundled = _bundled_rigctld()
    if bundled:
        return bundled

    found = shutil.which(RIGCTLD_EXE)
    if found:
        return found
    for d in _extra_search_dirs():
        cand = d / RIGCTLD_EXE
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    raise FileNotFoundError(
        "rigctld not found: no bundled copy, none on PATH or in the usual "
        "locations; install Hamlib or set the rigctld path in Settings")


def _subprocess_env(exe: str) -> dict[str, str]:
    """Environment for launching *exe* so it can load libraries beside it.

    A bundled rigctld sits next to whatever shared libraries it still needs
    (libhamlib when a shared build slipped through, plus third-party deps such
    as libusb that PyInstaller drops in the bundle). Those directories are not
    on the system loader path, so we point the loader at them explicitly. This
    is harmless for an external rigctld, whose own directory is already
    resolvable.
    """
    env = os.environ.copy()
    exe_dir = str(Path(exe).resolve().parent)
    dirs = [exe_dir]
    bundled = _bundled_hamlib_dir()
    if bundled is not None:
        dirs += [str(bundled / "lib"), str(bundled / "bin")]
    # PyInstaller drops rigctld's own auto-collected deps (libusb, …) in the
    # bundle root (sys._MEIPASS), not beside the binary — add it so a machine
    # with no system libusb can still load the bundled daemon.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(str(meipass))

    if sys.platform == "win32":
        var = "PATH"            # Windows resolves DLLs via PATH (+ the exe dir)
    elif sys.platform == "darwin":
        var = "DYLD_LIBRARY_PATH"
    else:
        var = "LD_LIBRARY_PATH"
    existing = env.get(var, "")
    env[var] = os.pathsep.join(dirs + ([existing] if existing else []))
    return env


def _free_port(host: str = "127.0.0.1") -> int:
    """Return a TCP port on *host* that is currently unused.

    The OS assigns a free port when we bind to port 0; we hand it straight
    to rigctld. There is a small window between closing this socket and
    rigctld binding the port, but on loopback that race is negligible and
    this is the standard way to reserve an ephemeral port.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, 0))
        return s.getsockname()[1]


class ManagedRigctld:
    """A rigctld subprocess owned and supervised by digiham.

    Usage::

        rigctld = ManagedRigctld(model=1035, device="/dev/ttyUSB0")
        host, port = rigctld.start()
        with RigctlClient(host, port) as rig:
            ...
        rigctld.stop()

    or as a context manager::

        with ManagedRigctld(model=1) as (host, port):
            ...
    """

    def __init__(
        self,
        model: int,
        device: str = "",
        baud: int = 0,
        *,
        rigctld_path: str = "",
        host: str = "127.0.0.1",
        extra_args: list[str] | None = None,
    ) -> None:
        self.model = model
        self.device = device
        self.baud = baud
        self.rigctld_path = rigctld_path
        self.host = host
        self.extra_args = list(extra_args or [])
        self.port = 0
        self._proc: subprocess.Popen | None = None
        self._log: tempfile.SpooledTemporaryFile | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, timeout: float = 10.0) -> tuple[str, int]:
        """Launch rigctld and block until it is listening.

        Returns the ``(host, port)`` to connect to. Idempotent: if the
        daemon is already running the existing address is returned.
        """
        if self.running:
            return self.host, self.port

        exe = find_rigctld(self.rigctld_path)
        self.port = _free_port(self.host)
        cmd = [exe, "-m", str(self.model),
               "-T", self.host, "-t", str(self.port)]
        if self.device:
            cmd += ["-r", self.device]
        if self.baud:
            cmd += ["-s", str(self.baud)]
        cmd += self.extra_args

        # rigctld is chatty and long-lived; send its output to a temp file so
        # a full pipe buffer can never block it, and so we can quote it back
        # if it dies during startup.
        self._log = tempfile.SpooledTemporaryFile(max_size=1 << 16, mode="w+b")
        # Detach from our process group so a Ctrl-C to digiham does not race
        # our own terminate(); on Windows the equivalent flag does the same.
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        logger.info("starting rigctld: %s", " ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=self._log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, env=_subprocess_env(exe), **kwargs)
        except OSError as e:
            self._close_log()
            raise RigctldStartError(f"could not launch {exe}: {e}") from e

        try:
            self._wait_ready(timeout)
        except Exception:
            self.stop()
            raise
        return self.host, self.port

    def _wait_ready(self, timeout: float) -> None:
        assert self._proc is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RigctldStartError(
                    f"rigctld exited during startup (code {self._proc.returncode})"
                    f"{self._log_tail()}")
            try:
                with socket.create_connection((self.host, self.port), timeout=0.5):
                    logger.info("rigctld listening on %s:%s", self.host, self.port)
                    return
            except OSError:
                time.sleep(0.1)
        raise RigctldStartError(
            f"rigctld did not start listening on {self.host}:{self.port} "
            f"within {timeout:g}s{self._log_tail()}")

    def _log_tail(self, limit: int = 500) -> str:
        """Return the tail of rigctld's captured output for error messages."""
        if self._log is None:
            return ""
        try:
            self._log.seek(0)
            data = self._log.read()
        except (OSError, ValueError):
            return ""
        text = data.decode("utf-8", "replace").strip()
        if not text:
            return ""
        return ": " + text[-limit:]

    def _close_log(self) -> None:
        if self._log is not None:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None

    def stop(self) -> None:
        """Terminate the daemon (if running) and release its resources."""
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                logger.warning("rigctld did not exit; killing it")
                proc.kill()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        self._close_log()

    def __enter__(self) -> tuple[str, int]:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# Rig model catalogue (rigctld -l)
# ---------------------------------------------------------------------------

# The status words Hamlib prints in the second-to-last column; used to find
# the column boundary because both the manufacturer and model names contain
# spaces and so can't be split on whitespace reliably.
_RIG_STATUS = {"Alpha", "Untested", "Beta", "Stable"}


class RigModel:
    """One entry from ``rigctld -l``: a selectable radio backend."""

    __slots__ = ("id", "name", "status")

    def __init__(self, id: int, name: str, status: str) -> None:
        self.id = id
        self.name = name        # "Yaesu FTDX-10", "Hamlib Dummy", …
        self.status = status    # Stable / Beta / Alpha / Untested

    def __repr__(self) -> str:
        return f"RigModel({self.id}, {self.name!r}, {self.status!r})"


_MODELS_CACHE: list[RigModel] | None = None


def _parse_model_line(line: str) -> RigModel | None:
    tokens = line.split()
    if len(tokens) < 5 or not tokens[0].isdigit():
        return None
    # scan from the right for the Status column; Version sits just left of it
    # and the manufacturer+model text is everything between the id and Version.
    for i in range(len(tokens) - 1, 0, -1):
        if tokens[i] in _RIG_STATUS:
            name = " ".join(tokens[1:i - 1])
            if not name:
                return None
            return RigModel(int(tokens[0]), name, tokens[i])
    return None


def list_rig_models(rigctld_path: str = "", refresh: bool = False) -> list[RigModel]:
    """Return the radios this Hamlib build supports, via ``rigctld -l``.

    The result is cached (the catalogue can't change without swapping the
    binary). Returns an empty list, rather than raising, if rigctld can't
    be found or run — callers fall back to a plain model-number entry.
    """
    global _MODELS_CACHE
    if _MODELS_CACHE is not None and not refresh:
        return _MODELS_CACHE
    try:
        exe = find_rigctld(rigctld_path)
        out = subprocess.run(
            [exe, "-l"], capture_output=True, text=True, timeout=10, check=True)
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as e:
        logger.warning("could not list rig models: %s", e)
        return []
    models: list[RigModel] = []
    for line in out.stdout.splitlines():
        m = _parse_model_line(line)
        if m is not None:
            models.append(m)
    models.sort(key=lambda m: m.id)
    _MODELS_CACHE = models
    return models


def rig_model_name(model_id: int, rigctld_path: str = "") -> str:
    """Human name for a model id, or ``"model <id>"`` if unknown."""
    for m in list_rig_models(rigctld_path):
        if m.id == model_id:
            return m.name
    return f"model {model_id}"
