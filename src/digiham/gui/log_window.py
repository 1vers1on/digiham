"""A QSO log viewer dialog with search, sorting and export."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..adif import Qso, QsoLog

_COLS = ["Date", "Time", "Call", "Band", "Mode", "Freq MHz", "Sent", "Rcvd", "Grid"]
# columns whose text should sort/right-align as numbers
_NUM_COLS = {5}
_RIGHT_COLS = {5, 6, 7}


def _fmt_date(d: str) -> str:
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d


def _fmt_time(t: str) -> str:
    return f"{t[0:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else t


class LogWindow(QDialog):
    def __init__(self, log: QsoLog, parent=None):
        super().__init__(parent)
        self.log = log
        self.setWindowTitle("digiham — QSO Log")
        self.resize(820, 460)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by call, grid, band, mode…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.count = QLabel()
        btn_export = QPushButton("Export ADIF…")
        btn_export.clicked.connect(lambda: self._export("adif"))
        btn_csv = QPushButton("Export CSV…")
        btn_csv.clicked.connect(lambda: self._export("csv"))
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)

        top = QHBoxLayout()
        top.addWidget(QLabel("Search:"))
        top.addWidget(self.search, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(self.count)
        bottom.addStretch(1)
        bottom.addWidget(btn_export)
        bottom.addWidget(btn_csv)
        bottom.addWidget(btn_close)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table)
        lay.addLayout(bottom)
        self.refresh()

    def refresh(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for q in reversed(self.log.records):
            self._add(q)
        self.table.setSortingEnabled(True)
        self._apply_filter()
        self._update_count()

    def add_qso(self, q: Qso) -> None:
        self.table.setSortingEnabled(False)
        self.table.insertRow(0)
        self._fill(0, q)
        self.table.setSortingEnabled(True)
        self._apply_filter()
        self._update_count()

    def _update_count(self) -> None:
        s = self.log.stats()
        shown = sum(not self.table.isRowHidden(r)
                    for r in range(self.table.rowCount()))
        prefix = f"showing {shown} of " if shown != s["qsos"] else ""
        self.count.setText(
            f"{prefix}{s['qsos']} QSOs · {s['calls']} calls · {s['dxcc']} DXCC · "
            f"{s['grids']} grids · {s['bands']} bands")

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().upper()
        for row in range(self.table.rowCount()):
            if not needle:
                self.table.setRowHidden(row, False)
                continue
            hay = " ".join(
                self.table.item(row, c).text().upper()
                for c in range(self.table.columnCount())
                if self.table.item(row, c) is not None)
            self.table.setRowHidden(row, needle not in hay)
        self._update_count()

    def _add(self, q: Qso) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._fill(row, q)

    def _fill(self, row: int, q: Qso) -> None:
        freq = f"{q.freq_mhz:.6f}".rstrip("0").rstrip(".")
        vals = [
            _fmt_date(q.qso_date), _fmt_time(q.time_on), q.call.upper(),
            q.band, q.mode, freq, q.rst_sent, q.rst_rcvd, q.gridsquare,
        ]
        for col, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if col in _NUM_COLS:
                # sort numerically rather than lexically
                try:
                    it.setData(Qt.ItemDataRole.EditRole, float(v))
                except ValueError:
                    pass
            if col in _RIGHT_COLS:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, it)

    def _export(self, fmt: str) -> None:
        if fmt == "csv":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export CSV", "digiham_log.csv", "CSV (*.csv)")
            writer, label = self.log.export_csv, "CSV"
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export ADIF", "digiham_export.adi", "ADIF (*.adi *.adif)")
            writer, label = self.log.export, "ADIF"
        if not path:
            return
        try:
            n = writer(path)
        except OSError as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return
        QMessageBox.information(self, "Export complete",
                                f"Exported {n} QSOs to {label}.")
