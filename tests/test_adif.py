"""Tests for ADIF round-tripping, import/merge, CSV export and log safety."""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from digiham.adif import (  # noqa: E402
    Qso, QsoLog, qso_to_adif, parse_adif, append_qso_file, daily_path,
)


def _qso(call="DL1ABC", date="20260704", time_on="143000", band="20m",
         mode="FT8", freq=14.075, grid="JO31") -> Qso:
    return Qso(call=call, qso_date=date, time_on=time_on, band=band,
               mode=mode, freq_mhz=freq, gridsquare=grid)


class RoundTripTests(unittest.TestCase):
    def test_ft4_submode_roundtrip(self):
        q = _qso(mode="FT4")
        (parsed,) = parse_adif(qso_to_adif(q))
        self.assertEqual(parsed.mode, "FT4")
        self.assertEqual(parsed.call, "DL1ABC")
        self.assertEqual(parsed.band, "20m")

    def test_ft8_has_no_submode(self):
        self.assertNotIn("SUBMODE", qso_to_adif(_qso(mode="FT8")))


class ImportTests(unittest.TestCase):
    def test_import_merges_and_dedups(self):
        with tempfile.TemporaryDirectory() as d:
            src = QsoLog(Path(d) / "src.adi")
            src.add(_qso(call="DL1ABC"))
            src.add(_qso(call="EA1XYZ", time_on="143100"))
            src.export(Path(d) / "exp.adi")

            dst = QsoLog(Path(d) / "dst.adi")
            dst.add(_qso(call="DL1ABC"))            # already present
            r = dst.import_adif(Path(d) / "exp.adi")
            self.assertEqual(r.added, 1)
            self.assertEqual(r.duplicates, 1)
            self.assertEqual(r.read, 2)
            self.assertEqual(len(dst.records), 2)

            # importing again adds nothing
            r2 = dst.import_adif(Path(d) / "exp.adi")
            self.assertEqual(r2.added, 0)
            self.assertEqual(r2.duplicates, 2)

    def test_import_persists_across_reload(self):
        with tempfile.TemporaryDirectory() as d:
            other = QsoLog(Path(d) / "o.adi")
            other.add(_qso(call="W1AW", grid="FN31"))
            other.export(Path(d) / "o_exp.adi")

            log = QsoLog(Path(d) / "log.adi")
            log.import_adif(Path(d) / "o_exp.adi")
            reloaded = QsoLog(Path(d) / "log.adi")
            self.assertIn("W1AW", reloaded.worked_calls())

    def test_import_dedups_within_file(self):
        with tempfile.TemporaryDirectory() as d:
            dup = Path(d) / "dup.adi"
            line = qso_to_adif(_qso(call="G0ABC"))
            dup.write_text(line + "\n" + line + "\n")
            log = QsoLog(Path(d) / "log.adi")
            r = log.import_adif(dup)
            self.assertEqual(r.added, 1)
            self.assertEqual(r.duplicates, 1)


class CsvExportTests(unittest.TestCase):
    def test_header_and_row(self):
        with tempfile.TemporaryDirectory() as d:
            log = QsoLog(Path(d) / "log.adi")
            log.add(_qso(call="DL1ABC", grid="JO31"))
            out = Path(d) / "out.csv"
            n = log.export_csv(out)
            self.assertEqual(n, 1)
            lines = out.read_text().splitlines()
            self.assertEqual(lines[0].split(",")[0], "CALL")
            self.assertIn("DL1ABC", lines[1])
            self.assertIn("JO31", lines[1])


class DailyFileTests(unittest.TestCase):
    def test_daily_path_uses_qso_date(self):
        p = daily_path("/logs", "20260704")
        self.assertEqual(p.name, "digiham_20260704.adi")

    def test_append_writes_header_once_then_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = daily_path(d, "20260704")
            append_qso_file(path, _qso(call="DL1ABC"))
            append_qso_file(path, _qso(call="EA1XYZ", time_on="143100"))
            text = path.read_text()
            self.assertEqual(text.count("<EOH>"), 1)   # one header
            self.assertEqual(text.count("<EOR>"), 2)   # two QSOs
            self.assertIn("DL1ABC", text)
            self.assertIn("EA1XYZ", text)


class SafetyTests(unittest.TestCase):
    def test_failed_write_does_not_desync_memory(self):
        if os.geteuid() == 0:
            self.skipTest("root bypasses directory permissions")
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "ro"
            sub.mkdir()
            log = QsoLog(sub / "log.adi")
            os.chmod(sub, stat.S_IRUSR | stat.S_IXUSR)
            try:
                with self.assertRaises(OSError):
                    log.add(_qso(call="ZZ9ZZ"))
                self.assertEqual(len(log.records), 0)
            finally:
                os.chmod(sub, stat.S_IRWXU)


if __name__ == "__main__":
    unittest.main()
