"""Tests for developer-callsign detection (decode highlighting)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham import devs  # noqa: E402


class DevTests(unittest.TestCase):
    def test_known_dev(self):
        self.assertTrue(devs.is_dev("W4NYA"))

    def test_case_insensitive(self):
        self.assertTrue(devs.is_dev("w4nya"))

    def test_suffix_stripped(self):
        self.assertTrue(devs.is_dev("W4NYA/P"))
        self.assertTrue(devs.is_dev("W4NYA/QRP"))

    def test_non_dev(self):
        self.assertFalse(devs.is_dev("K1ABC"))

    def test_empty(self):
        self.assertFalse(devs.is_dev(""))


if __name__ == "__main__":
    unittest.main()
