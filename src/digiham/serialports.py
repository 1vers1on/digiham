"""Cross-platform serial/COM port enumeration and hotplug helpers.

Radios show up as a USB-serial (CAT) port whose OS name is not stable:
the same rig can be ``/dev/ttyUSB0`` today and ``/dev/ttyUSB1`` tomorrow,
``/dev/cu.usbserial-XXXX`` on macOS, or ``COM5`` on Windows. To spare the
user from hand-editing that path, this module can list the ports, test
whether a given one is present right now, and pick the most likely radio
port automatically.

Enumeration is delegated to :mod:`pyserial` (``serial.tools.list_ports``),
which knows how to walk sysfs, IOKit and the Windows registry. If pyserial
is somehow unavailable we fall back to globbing the usual device nodes on
POSIX so the app still limps along.
"""

from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass

AUTO = "auto"   # rig_device sentinel: pick a USB-serial port automatically


@dataclass(frozen=True)
class SerialPort:
    device: str          # path/name to hand to rigctld (-r)
    description: str      # human name, e.g. "CP2102 USB to UART Bridge"
    hwid: str = ""        # VID:PID etc., "" if unknown
    is_usb: bool = False  # a USB device (i.e. very likely a radio's CAT port)

    @property
    def label(self) -> str:
        if self.description and self.description != "n/a":
            return f"{self.device} — {self.description}"
        return self.device


def _looks_like_usb(device: str) -> bool:
    d = device.lower()
    return any(k in d for k in ("usb", "acm", "cu.usbserial", "cu.usbmodem", "wchusb"))


def list_ports(usb_first: bool = True) -> list[SerialPort]:
    """Return the serial ports currently present on this machine.

    USB-serial adapters (the usual radio interface) are sorted ahead of
    legacy/native ports when *usb_first* is set.
    """
    ports = _list_via_pyserial()
    if ports is None:
        ports = _list_via_glob()
    if usb_first:
        # USB devices first, then by device name for a stable order
        ports.sort(key=lambda p: (not p.is_usb, p.device))
    return ports


def _list_via_pyserial() -> list[SerialPort] | None:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return None
    out: list[SerialPort] = []
    for p in lp.comports():
        hwid = "" if p.hwid in (None, "n/a") else p.hwid
        is_usb = p.vid is not None or _looks_like_usb(p.device)
        desc = p.description or ""
        out.append(SerialPort(p.device, desc, hwid, is_usb))
    return out


def _list_via_glob() -> list[SerialPort]:
    """POSIX fallback if pyserial is missing (no Windows equivalent)."""
    if sys.platform == "win32":
        return [SerialPort(f"COM{i}", "") for i in range(1, 21)]
    patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usb*",
                "/dev/cu.*serial*", "/dev/ttyS*"]
    seen: list[SerialPort] = []
    for pat in patterns:
        for dev in sorted(glob.glob(pat)):
            seen.append(SerialPort(dev, "", is_usb=_looks_like_usb(dev)))
    return seen


def port_exists(device: str) -> bool:
    """True if *device* is a serial port that is present right now."""
    if not device or device == AUTO:
        return False
    # A live enumeration is the reliable cross-platform check; on POSIX a
    # quick node test avoids the scan for the common case.
    if sys.platform != "win32" and os.path.exists(device):
        return True
    return any(p.device == device for p in list_ports(usb_first=False))


def auto_port() -> str | None:
    """Best guess at the radio's port: the first USB-serial device found.

    Returns ``None`` when nothing suitable is plugged in.
    """
    usb = [p for p in list_ports() if p.is_usb]
    return usb[0].device if usb else None


def resolve_device(setting: str) -> tuple[str, bool]:
    """Turn a stored ``rig_device`` setting into an actual device path.

    Returns ``(device, needs_device)`` where *device* is what to pass to
    rigctld's ``-r`` (``""`` means "don't pass one") and *needs_device*
    says whether a serial port must be present before we try to start:

    * ``""``      -> ("", False)          network/SDR rig, no serial port
    * ``"auto"``  -> (<first USB port> or "", True)
    * ``"/dev/…"``-> (that path, True)     an explicit port
    """
    if not setting:
        return "", False
    if setting == AUTO:
        return auto_port() or "", True
    return setting, True
