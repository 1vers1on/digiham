"""Tests for ARRL Field Day: message parsing, generation and sequencing."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham import sequencer as seq  # noqa: E402
from digiham.config import Config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_fd_exchange_combines_class_and_section(self):
        self.assertEqual(Config(fd_class="3a", fd_section="ema").fd_exchange(),
                         "3A EMA")

    def test_fd_exchange_empty_when_incomplete(self):
        self.assertEqual(Config(fd_class="3A", fd_section="").fd_exchange(), "")


class ParseTests(unittest.TestCase):
    def test_bare_exchange(self):
        pm = seq.parse("K1ABC W9XYZ 3A EMA")
        self.assertEqual(pm.kind, seq.K_EXCH)
        self.assertEqual(pm.exch, "3A EMA")
        self.assertEqual(pm.to, "K1ABC")
        self.assertEqual(pm.de, "W9XYZ")

    def test_rogered_exchange(self):
        pm = seq.parse("K1ABC W9XYZ R 3A EMA")
        self.assertEqual(pm.kind, seq.K_REXCH)
        self.assertEqual(pm.exch, "3A EMA")

    def test_cq_fd(self):
        pm = seq.parse("CQ FD K1ABC FN42")
        self.assertTrue(pm.is_cq)
        self.assertEqual(pm.cq_dir, "FD")
        self.assertEqual(pm.de, "K1ABC")
        self.assertEqual(pm.grid, "FN42")

    def test_dx_section(self):
        pm = seq.parse("K1ABC W9XYZ 1D DX")
        self.assertEqual(pm.kind, seq.K_EXCH)
        self.assertEqual(pm.exch, "1D DX")

    def test_report_not_mistaken_for_exchange(self):
        pm = seq.parse("W9XYZ K1ABC -12")
        self.assertEqual(pm.kind, seq.K_REPORT)


class MessageGenTests(unittest.TestCase):
    def test_message_set(self):
        msgs = seq.field_day_messages("K1ABC", "FN42", "W9XYZ", "3A EMA")
        self.assertEqual(msgs[0], "W9XYZ K1ABC 3A EMA")     # Tx1
        self.assertEqual(msgs[2], "W9XYZ K1ABC R 3A EMA")   # Tx3
        self.assertEqual(msgs[3], "W9XYZ K1ABC RR73")       # Tx4
        self.assertEqual(msgs[5], "CQ FD K1ABC FN42")       # Tx6

    def test_sequencer_uses_fd_messages(self):
        s = seq.Sequencer("K1ABC", "FN42", contest="FD", my_exch="3A EMA")
        s.start_cq()
        self.assertEqual(s.current_message(), "CQ FD K1ABC FN42")

    def test_fd_inert_without_exchange(self):
        # Field Day must not transmit until a class + section is set.
        s = seq.Sequencer("K1ABC", "FN42", contest="FD", my_exch="")
        s.start_cq()
        self.assertEqual(s.messages, [""] * 6)
        self.assertEqual(s.current_message(), "")


class SequenceTests(unittest.TestCase):
    def test_cq_station_flow_logs_exchange(self):
        s = seq.Sequencer("K1ABC", "FN42", contest="FD", my_exch="2B EMA")
        s.start_cq()
        # a caller answers our CQ with their class/section
        log = s.engage(seq.parse("K1ABC W9XYZ 6A WI"), -10)
        self.assertIsNone(log)
        self.assertEqual(s.current_message(), "W9XYZ K1ABC R 2B EMA")  # Tx3
        s.on_transmitted(3)
        # they roger with RR73 -> we log
        log = s.on_decode(seq.parse("K1ABC W9XYZ RR73"), -10)
        self.assertIsNotNone(log)
        self.assertEqual(log.dxcall, "W9XYZ")
        self.assertEqual(log.dxexch, "6A WI")

    def test_caller_flow_logs_exchange(self):
        s = seq.Sequencer("K1ABC", "FN42", contest="FD", my_exch="2B EMA")
        s.answer_cq("W9XYZ", "", -8)
        self.assertEqual(s.current_message(), "W9XYZ K1ABC 2B EMA")   # Tx1
        s.on_transmitted(1)
        # CQ station rogers our exchange and sends its own
        log = s.on_decode(seq.parse("K1ABC W9XYZ R 6A WI"), -8)
        self.assertIsNone(log)
        self.assertEqual(s.current_message(), "W9XYZ K1ABC RR73")     # Tx4
        log = s.on_transmitted(4)
        self.assertIsNotNone(log)
        self.assertEqual(log.dxexch, "6A WI")

    def test_normal_mode_unaffected(self):
        s = seq.Sequencer("K1ABC", "FN42")   # no contest
        s.start_cq()
        self.assertEqual(s.current_message(), "CQ K1ABC FN42")
        log = s.engage(seq.parse("K1ABC W9XYZ EM73"), -10)
        self.assertIsNone(log)
        self.assertEqual(s.current_message(), "W9XYZ K1ABC -10")      # Tx2 report


if __name__ == "__main__":
    unittest.main()
