"""Example plugin: append every logged QSO to a running CSV file.

Demonstrates on_qso_logged plus ctx.data_dir() for per-plugin storage.
The file lands in the plugin's private data directory, e.g.
``~/.config/digiham/plugin_data/qso-csv/qsos.csv``.
"""

import csv

from digiham.plugins import Plugin

_FIELDS = ["date", "time", "call", "band", "mode", "freq_mhz", "grid"]


class QsoCsv(Plugin):
    name = "qso-csv"
    version = "1.0"
    description = "Append each logged QSO to qsos.csv"

    def on_load(self):
        self.path = self.ctx.data_dir(self.name) / "qsos.csv"
        if not self.path.exists():
            with self.path.open("w", newline="") as f:
                csv.writer(f).writerow(_FIELDS)

    def on_qso_logged(self, qso):
        with self.path.open("a", newline="") as f:
            csv.writer(f).writerow([
                qso.qso_date, qso.time_on, qso.call.upper(), qso.band,
                qso.mode, f"{qso.freq_mhz:g}", qso.gridsquare,
            ])
        self.ctx.status(f"qso-csv: saved {qso.call}")
