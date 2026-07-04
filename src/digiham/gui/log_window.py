"""A simple QSO log viewer dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..adif import Qso, QsoLog

_COLS = ["Date", "Time", "Call", "Band", "Mode", "Freq MHz", "Sent", "Rcvd", "Grid"]


class LogWindow(QDialog):
    def __init__(self, log: QsoLog, parent=None):
        super().__init__(parent)
        self.log = log
        self.setWindowTitle("digiham — QSO Log")
        self.resize(760, 420)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.count = QLabel()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        top = QHBoxLayout()
        top.addWidget(self.count)
        top.addStretch(1)
        top.addWidget(btn_close)

        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        lay.addLayout(top)
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        for q in reversed(self.log.records):
            self._add(q)
        self._update_count()

    def add_qso(self, q: Qso) -> None:
        self.table.insertRow(0)
        self._fill(0, q)
        self._update_count()

    def _update_count(self) -> None:
        s = self.log.stats()
        self.count.setText(
            f"{s['qsos']} QSOs · {s['calls']} calls · {s['dxcc']} DXCC · "
            f"{s['grids']} grids · {s['bands']} bands")

    def _add(self, q: Qso) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._fill(row, q)

    def _fill(self, row: int, q: Qso) -> None:
        vals = [
            q.qso_date, q.time_on, q.call.upper(), q.band, q.mode,
            f"{q.freq_mhz:.6f}".rstrip("0").rstrip("."),
            q.rst_sent, q.rst_rcvd, q.gridsquare,
        ]
        for col, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if col in (5, 6, 7):
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, it)
