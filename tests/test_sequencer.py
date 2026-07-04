"""Unit tests for the QSO auto-sequencer state machine.

Pure logic, no Qt/audio — runs under either ``pytest`` or the stdlib
``unittest`` runner:

    .venv/bin/python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham import sequencer as seq  # noqa: E402


MY = "W4NYA"
MYGRID = "EM73"


def new_seq():
    s = seq.Sequencer(MY, MYGRID)
    s.start_cq()
    return s


def rx(s, text, snr=-12):
    """Feed a decoded message addressed to us via engage()."""
    return s.engage(seq.parse(text), snr)


class ParseTests(unittest.TestCase):
    def test_cq_with_grid(self):
        pm = seq.parse("CQ K1ABC FN42")
        self.assertTrue(pm.is_cq)
        self.assertEqual(pm.de, "K1ABC")
        self.assertEqual(pm.grid, "FN42")
        self.assertEqual(pm.kind, seq.K_CQ)

    def test_directional_cq(self):
        pm = seq.parse("CQ DX K1ABC FN42")
        self.assertEqual(pm.cq_dir, "DX")
        self.assertEqual(pm.de, "K1ABC")

    def test_grid_answer(self):
        pm = seq.parse("W4NYA K1ABC EM73")
        self.assertEqual(pm.to, "W4NYA")
        self.assertEqual(pm.de, "K1ABC")
        self.assertEqual(pm.kind, seq.K_GRID)

    def test_report_vs_rreport(self):
        self.assertEqual(seq.parse("W4NYA K1ABC -12").kind, seq.K_REPORT)
        self.assertEqual(seq.parse("W4NYA K1ABC R-12").kind, seq.K_RREPORT)
        self.assertEqual(seq.parse("W4NYA K1ABC -12").report, -12)
        self.assertEqual(seq.parse("W4NYA K1ABC R-12").report, -12)

    def test_rogers_and_73(self):
        self.assertEqual(seq.parse("W4NYA K1ABC RR73").kind, seq.K_RR73)
        self.assertEqual(seq.parse("W4NYA K1ABC RRR").kind, seq.K_RRR)
        self.assertEqual(seq.parse("W4NYA K1ABC 73").kind, seq.K_73)


class ParseWsprTests(unittest.TestCase):
    """WSPR is 'CALL GRID DBM', not an FT8 exchange, and must not be read by
    parse() (which would mistake the grid for the sender's callsign)."""

    def test_standard_wspr(self):
        pm = seq.parse_wspr("W4NYA FM18 37")
        self.assertEqual(pm.de, "W4NYA")
        self.assertEqual(pm.grid, "FM18")
        self.assertEqual(pm.to, "")          # no addressee: not directed at us
        self.assertFalse(pm.is_cq)

    def test_ft8_parse_would_misread_the_grid_as_a_call(self):
        # Guards the exact bug this parser exists to avoid.
        self.assertEqual(seq.parse("W4NYA FM18 37").de, "FM18")
        self.assertEqual(seq.parse_wspr("W4NYA FM18 37").de, "W4NYA")

    def test_type2_call_only(self):
        pm = seq.parse_wspr("PJ4/K1ABC")
        self.assertEqual(pm.de, "PJ4/K1ABC")
        self.assertEqual(pm.grid, "")

    def test_hashed_call_strips_brackets(self):
        pm = seq.parse_wspr("<PJ4/K1ABC> FK52")
        self.assertEqual(pm.de, "PJ4/K1ABC")
        self.assertEqual(pm.grid, "FK52")

    def test_empty(self):
        pm = seq.parse_wspr("")
        self.assertEqual(pm.de, "")
        self.assertEqual(pm.grid, "")


class CqAnsweredTests(unittest.TestCase):
    """We call CQ; a station answers. The regression the user hit: clicking
    the answer must send a *report*, not our own grid back."""

    def test_answer_with_grid_sends_report_not_grid(self):
        s = new_seq()
        log = rx(s, "W4NYA K1ABC EM12", snr=-8)
        self.assertIsNone(log)
        self.assertTrue(s.in_qso)
        self.assertTrue(s.calling_cq)          # we were the CQ station
        self.assertEqual(s.dxcall, "K1ABC")
        self.assertEqual(s.dxgrid, "EM12")
        self.assertEqual(s.next_tx, 2)         # Tx2 = report
        self.assertEqual(s.current_message(), "K1ABC W4NYA -08")

    def test_bare_answer_no_grid_still_reports(self):
        s = new_seq()
        rx(s, "W4NYA K1ABC", snr=-3)
        self.assertEqual(s.next_tx, 2)
        self.assertEqual(s.current_message(), "K1ABC W4NYA -03")

    def test_full_qso_as_cq_station(self):
        s = new_seq()
        rx(s, "W4NYA K1ABC EM12", snr=-8)       # they answer -> we send report
        self.assertEqual(s.current_message(), "K1ABC W4NYA -08")
        # they roger our report (R-15) -> we send RR73
        log = s.on_decode(seq.parse("W4NYA K1ABC R-15"), -8)
        self.assertIsNone(log)
        self.assertEqual(s.report_in, -15)
        self.assertEqual(s.next_tx, 4)
        self.assertEqual(s.current_message(), "K1ABC W4NYA RR73")
        # we transmit RR73 (Tx4) -> QSO logged, back to CQ
        log = s.on_transmitted(4)
        self.assertIsNotNone(log)
        self.assertEqual(log.dxcall, "K1ABC")
        self.assertEqual(log.report_sent, -8)
        self.assertEqual(log.report_recv, -15)
        self.assertFalse(s.in_qso)
        self.assertEqual(s.next_tx, 6)


class AnsweringCqTests(unittest.TestCase):
    """We answer somebody else's CQ (we are the caller)."""

    def test_full_qso_as_caller(self):
        s = new_seq()
        s.answer_cq("K1ABC", "FN42", -10)       # we open with our grid
        self.assertFalse(s.calling_cq)
        self.assertEqual(s.next_tx, 1)
        self.assertEqual(s.current_message(), "K1ABC W4NYA EM73")
        # they send us a report -> we roger + report (Tx3)
        s.on_decode(seq.parse("W4NYA K1ABC -07"), -10)
        self.assertEqual(s.report_in, -7)
        self.assertEqual(s.next_tx, 3)
        self.assertEqual(s.current_message(), "K1ABC W4NYA R-10")
        # they roger (RR73) -> we send 73 and log
        log = s.on_decode(seq.parse("W4NYA K1ABC RR73"), -10)
        self.assertIsNotNone(log)
        self.assertEqual(log.report_sent, -10)
        self.assertEqual(log.report_recv, -7)
        self.assertEqual(s.next_tx, 5)
        self.assertEqual(s.current_message(), "K1ABC W4NYA 73")
        # after we send 73, QSO ends
        s.on_transmitted(5)
        self.assertFalse(s.in_qso)
        self.assertEqual(s.next_tx, 6)


class EngageRoleInferenceTests(unittest.TestCase):
    def test_report_to_us_makes_us_the_caller(self):
        s = new_seq()
        # picking up a station that reports us straight away
        rx(s, "W4NYA K1ABC -05", snr=-9)
        self.assertFalse(s.calling_cq)
        self.assertEqual(s.report_in, -5)
        self.assertEqual(s.next_tx, 3)          # roger + report
        self.assertEqual(s.current_message(), "K1ABC W4NYA R-09")

    def test_rr73_pickup_logs_and_signs_off(self):
        s = new_seq()
        log = rx(s, "W4NYA K1ABC RR73", snr=-9)
        self.assertIsNotNone(log)
        self.assertEqual(log.dxcall, "K1ABC")
        self.assertEqual(s.next_tx, 5)          # 73

    def test_engage_ignores_our_own_call(self):
        s = new_seq()
        self.assertIsNone(rx(s, "W4NYA W4NYA EM73"))
        self.assertFalse(s.in_qso)

    def test_engage_does_not_flip_role_mid_qso(self):
        s = new_seq()
        rx(s, "W4NYA K1ABC EM12", snr=-8)       # we are CQ station
        self.assertTrue(s.calling_cq)
        # same DX repeats their grid (didn't hear our report): stay CQ
        # station, keep resending the report.
        rx(s, "W4NYA K1ABC EM12", snr=-8)
        self.assertTrue(s.calling_cq)
        self.assertEqual(s.next_tx, 2)


class LoggingGuardTests(unittest.TestCase):
    def test_log_emitted_once(self):
        s = new_seq()
        rx(s, "W4NYA K1ABC EM12", snr=-8)
        s.on_decode(seq.parse("W4NYA K1ABC R-15"), -8)
        first = s.on_transmitted(4)
        self.assertIsNotNone(first)
        # a stray repeat must not double-log
        again = s.on_transmitted(4)
        self.assertIsNone(again)


if __name__ == "__main__":
    unittest.main()
