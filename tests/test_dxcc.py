"""Tests for the lightweight DXCC prefix resolver."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham import dxcc  # noqa: E402


class LookupTests(unittest.TestCase):
    def test_common_countries(self):
        cases = {
            "W4NYA": ("United States", "NA"),
            "K1ABC": ("United States", "NA"),
            "VE3XYZ": ("Canada", "NA"),
            "G0ABC": ("England", "EU"),
            "GM4ABC": ("Scotland", "EU"),   # longer prefix beats "G"
            "GW0XYZ": ("Wales", "EU"),
            "DL1ABC": ("Germany", "EU"),
            "F5ABC": ("France", "EU"),
            "JA1XYZ": ("Japan", "AS"),
            "VK2DEF": ("Australia", "OC"),
            "ZL1ABC": ("New Zealand", "OC"),
            "PY2ABC": ("Brazil", "SA"),
            "ZS6ABC": ("South Africa", "AF"),
        }
        for call, (name, cont) in cases.items():
            e = dxcc.lookup(call)
            self.assertIsNotNone(e, call)
            self.assertEqual(e.name, name, call)
            self.assertEqual(e.continent, cont, call)

    def test_longest_prefix_wins(self):
        # KH6 (Hawaii) must beat the generic K (United States).
        self.assertEqual(dxcc.country("KH6XYZ"), "Hawaii")
        self.assertEqual(dxcc.country("KL7ABC"), "Alaska")
        self.assertEqual(dxcc.country("KP4XYZ"), "Puerto Rico")
        # EA8 (Canary Is) beats EA (Spain) and is in Africa.
        self.assertEqual(dxcc.continent("EA8ABC"), "AF")

    def test_portable_override_prefix(self):
        # Operating-country prefix in front wins.
        self.assertEqual(dxcc.country("F/W1ABC"), "France")
        # Override after the call, too.
        self.assertEqual(dxcc.country("W1ABC/VP9"), "Bermuda")

    def test_portable_suffix_is_home_country(self):
        self.assertEqual(dxcc.country("W1ABC/P"), "United States")
        self.assertEqual(dxcc.country("G0ABC/M"), "England")
        self.assertEqual(dxcc.country("K1ABC/4"), "United States")

    def test_unresolved(self):
        self.assertIsNone(dxcc.lookup(""))
        self.assertEqual(dxcc.country("CQ"), "")

    def test_continent_helper(self):
        self.assertEqual(dxcc.continent("JA1ABC"), "AS")
        self.assertEqual(dxcc.continent("LU1ABC"), "SA")


if __name__ == "__main__":
    unittest.main()
