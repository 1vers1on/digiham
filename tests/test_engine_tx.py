"""Behavioural test for 'disable Tx after the QSO completes'.

Exercises RadioEngine._on_tx_finished against a lightweight stub so the
Tx-disable rule can be checked without a Qt event loop or audio.
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham.engine import RadioEngine  # noqa: E402
from digiham.config import Config  # noqa: E402


class _Seq:
    def on_transmitted(self, idx):
        return None


def _stub(disable, tx_enabled=True):
    s = types.SimpleNamespace()
    s.cfg = Config(disable_tx_after_qso=disable, auto_log=False)
    s.seq = _Seq()
    s.tx_enabled = tx_enabled
    s.enabled_calls = []
    s._end_tx = lambda: None
    s._emit_tx_messages = lambda: None
    s._emit_seq_state = lambda: None
    s._commit_log = lambda *a, **k: None
    s.enable_tx = lambda on: s.enabled_calls.append(on)
    s._on_tx_finished = lambda idx: RadioEngine._on_tx_finished(s, idx)
    return s


class DisableTxAfterQsoTests(unittest.TestCase):
    def test_disables_after_rr73_and_73(self):
        for idx in (4, 5):
            s = _stub(disable=True)
            s._on_tx_finished(idx)
            self.assertEqual(s.enabled_calls, [False], f"idx={idx}")

    def test_not_disabled_for_mid_qso_messages(self):
        for idx in (1, 2, 3, 6):
            s = _stub(disable=True)
            s._on_tx_finished(idx)
            self.assertEqual(s.enabled_calls, [], f"idx={idx}")

    def test_option_off_never_disables(self):
        s = _stub(disable=False)
        s._on_tx_finished(5)
        self.assertEqual(s.enabled_calls, [])

    def test_no_disable_when_tx_already_off(self):
        s = _stub(disable=True, tx_enabled=False)
        s._on_tx_finished(5)
        self.assertEqual(s.enabled_calls, [])


if __name__ == "__main__":
    unittest.main()
