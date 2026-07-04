"""Tests for serial-port helpers and device resolution."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham import serialports as sp  # noqa: E402


class ResolveDeviceTests(unittest.TestCase):
    def test_none_needs_no_device(self):
        self.assertEqual(sp.resolve_device(""), ("", False))

    def test_explicit_path_needs_device(self):
        self.assertEqual(sp.resolve_device("/dev/ttyUSB0"), ("/dev/ttyUSB0", True))

    def test_auto_uses_detected_port(self):
        real = sp.auto_port
        try:
            sp.auto_port = lambda: "/dev/ttyRADIO"
            self.assertEqual(sp.resolve_device(sp.AUTO), ("/dev/ttyRADIO", True))
            sp.auto_port = lambda: None
            self.assertEqual(sp.resolve_device(sp.AUTO), ("", True))
        finally:
            sp.auto_port = real


class SerialPortTests(unittest.TestCase):
    def test_label_with_description(self):
        p = sp.SerialPort("/dev/ttyUSB0", "CP2102 UART", is_usb=True)
        self.assertEqual(p.label, "/dev/ttyUSB0 — CP2102 UART")

    def test_label_without_description(self):
        self.assertEqual(sp.SerialPort("/dev/ttyS0", "n/a").label, "/dev/ttyS0")

    def test_usb_heuristic(self):
        self.assertTrue(sp._looks_like_usb("/dev/ttyUSB3"))
        self.assertTrue(sp._looks_like_usb("/dev/cu.usbserial-10"))
        self.assertFalse(sp._looks_like_usb("/dev/ttyS0"))


class PortExistsTests(unittest.TestCase):
    def test_blank_and_auto_are_not_ports(self):
        self.assertFalse(sp.port_exists(""))
        self.assertFalse(sp.port_exists(sp.AUTO))


if __name__ == "__main__":
    unittest.main()
