"""Tests for the ALL.TXT spot logger."""

import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham import spotlog  # noqa: E402


WHEN = dt.datetime(2026, 7, 4, 14, 30, 0, tzinfo=dt.timezone.utc)


class FormatTests(unittest.TestCase):
    def test_decode_line(self):
        line = spotlog.format_line(WHEN, 14.074, False, "FT8", -10, 0.2,
                                   1633, "CQ DL1ABC JO31")
        self.assertTrue(line.startswith("260704_143000"))
        self.assertIn("Rx", line)
        self.assertIn("FT8", line)
        self.assertIn("CQ DL1ABC JO31", line)
        self.assertIn("-10", line)

    def test_tx_marked(self):
        line = spotlog.format_line(WHEN, 14.074, True, "FT8", 0, 0, 1500,
                                   "K1ABC W4NYA -12")
        self.assertIn(" Tx ", line)

    def test_naive_datetime_treated_as_utc_aware(self):
        # An aware datetime in another zone still formats in UTC.
        est = dt.timezone(dt.timedelta(hours=-5))
        when = dt.datetime(2026, 7, 4, 9, 30, 0, tzinfo=est)  # 14:30 UTC
        line = spotlog.format_line(when, 7.074, False, "FT4", -5, 0.0, 900, "x")
        self.assertTrue(line.startswith("260704_143000"))


class WriteTests(unittest.TestCase):
    def test_append_and_toggle(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ALL.TXT")
            log = spotlog.SpotLog(path, enabled=True)
            log.log_decode(WHEN, 14.074, "FT8", -1, 0.0, 1500, "CQ K1ABC FN42")
            log.log_tx(WHEN, 14.074, "FT8", 1500, "K1ABC W4NYA -12")
            lines = Path(path).read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("Rx", lines[0])
            self.assertIn("Tx", lines[1])

            log.enabled = False
            log.log_decode(WHEN, 14.074, "FT8", -1, 0.0, 1500, "ignored")
            self.assertEqual(len(Path(path).read_text().splitlines()), 2)

    def test_disabled_never_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ALL.TXT")
            log = spotlog.SpotLog(path, enabled=False)
            log.log_decode(WHEN, 14.074, "FT8", -1, 0.0, 1500, "x")
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
