"""Tests for rigctld helpers: model-list parsing and binary discovery."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham import rigctl  # noqa: E402


SAMPLE = """\
 Rig #  Mfg                    Model                   Version         Status      Macro
     1  Hamlib                 Dummy                   20240709.0      Stable      RIG_MODEL_DUMMY
     2  Hamlib                 NET rigctl              20250211.0      Stable      RIG_MODEL_NETRIGCTL
    10  N2ADR James Ahlstrom   Quisk                   20230709.0      Stable      RIG_MODEL_QUISK
  1042  Yaesu                  FTDX-10                 20241118.9      Stable      RIG_MODEL_FTDX10
  2034  Kenwood                TM-D710(G)              20250515.6      Stable      RIG_MODEL_TMD710
 42001  Harris                 PRC-138                 1.0.6           Alpha       RIG_MODEL_PRC138
"""


class ModelParseTests(unittest.TestCase):
    def test_parses_simple_line(self):
        m = rigctl._parse_model_line(SAMPLE.splitlines()[1])
        self.assertEqual(m.id, 1)
        self.assertEqual(m.name, "Hamlib Dummy")
        self.assertEqual(m.status, "Stable")

    def test_multiword_model_and_mfg(self):
        by_id = {rigctl._parse_model_line(ln).id: rigctl._parse_model_line(ln)
                 for ln in SAMPLE.splitlines()[1:]}
        self.assertEqual(by_id[2].name, "Hamlib NET rigctl")
        self.assertEqual(by_id[10].name, "N2ADR James Ahlstrom Quisk")
        self.assertEqual(by_id[1042].name, "Yaesu FTDX-10")
        self.assertEqual(by_id[2034].name, "Kenwood TM-D710(G)")

    def test_non_stable_status(self):
        m = rigctl._parse_model_line(SAMPLE.splitlines()[6])
        self.assertEqual(m.id, 42001)
        self.assertEqual(m.status, "Alpha")
        self.assertEqual(m.name, "Harris PRC-138")

    def test_header_and_garbage_ignored(self):
        self.assertIsNone(rigctl._parse_model_line(SAMPLE.splitlines()[0]))
        self.assertIsNone(rigctl._parse_model_line(""))
        self.assertIsNone(rigctl._parse_model_line("not a model line"))


class DiscoveryTests(unittest.TestCase):
    def test_explicit_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            rigctl.find_rigctld("/definitely/not/here/rigctld")

    def test_free_port_is_usable_int(self):
        p = rigctl._free_port()
        self.assertIsInstance(p, int)
        self.assertGreater(p, 0)


class NormalizeModeTests(unittest.TestCase):
    def test_panel_alias_maps_to_hamlib(self):
        self.assertEqual(rigctl.normalize_mode("DATA-U"), "PKTUSB")

    def test_blank_passes_through(self):
        self.assertEqual(rigctl.normalize_mode(""), "")

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            rigctl.normalize_mode("NOTAMODE")


if __name__ == "__main__":
    unittest.main()
