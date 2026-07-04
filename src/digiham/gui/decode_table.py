"""The decode tables (Band Activity / Rx Frequency)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem

from ..engine import DecodeRow
from .theme import PALETTE

_COLS = ["UTC", "dB", "DT", "Freq", "Message"]
_MAX_ROWS = 1000


class DecodeTable(QTableWidget):
    activated = Signal(object)      # DecodeRow

    def __init__(self, parent=None):
        super().__init__(0, len(_COLS), parent)
        self.setHorizontalHeaderLabels(_COLS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setAlternatingRowColors(True)
        h = self.horizontalHeader()
        h.setStretchLastSection(True)
        for i, wdt in enumerate((60, 42, 48, 56)):
            self.setColumnWidth(i, wdt)
        self.itemDoubleClicked.connect(self._on_double)

    def _on_double(self, item: QTableWidgetItem) -> None:
        row = item.row()
        data = self.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if isinstance(data, DecodeRow):
            self.activated.emit(data)

    def add_decode(self, d: DecodeRow) -> None:
        row = self.rowCount()
        self.insertRow(row)
        freq = f"{d.freq_audio:4.0f}"
        cells = [d.utc_hhmmss, f"{d.snr:+.0f}", f"{d.dt:+.1f}", freq, d.message]
        bg, fg, bold = self._style(d)
        for col, text in enumerate(cells):
            it = QTableWidgetItem(text)
            if bg is not None:
                it.setBackground(QBrush(QColor(bg)))
            if fg is not None:
                it.setForeground(QBrush(QColor(fg)))
            if bold and col == 4:
                f = QFont(); f.setBold(True); it.setFont(f)
            if col in (1, 2, 3):
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(row, col, it)
        self.item(row, 0).setData(Qt.ItemDataRole.UserRole, d)

        if self.rowCount() > _MAX_ROWS:
            self.removeRow(0)
        self.scrollToBottom()

    @staticmethod
    def _style(d: DecodeRow):
        if d.to_me:
            return PALETTE["hl_tome"], PALETTE["magenta"], True
        if d.is_cq and d.new_call:
            return PALETTE["hl_cq"], PALETTE["green"], True
        if d.is_cq:
            return PALETTE["hl_cq"], PALETTE["green"], False
        if d.new_call:
            return PALETTE["hl_newcall"], None, False
        return None, None, False

    def mark_cycle(self) -> None:
        """Insert a faint separator row at a period boundary."""
        if self.rowCount() == 0:
            return
        row = self.rowCount()
        self.insertRow(row)
        it = QTableWidgetItem("")
        it.setBackground(QBrush(QColor(PALETTE["border"])))
        self.setItem(row, 0, it)
        self.setSpan(row, 0, 1, len(_COLS))
        self.setRowHeight(row, 2)
        if self.rowCount() > _MAX_ROWS:
            self.removeRow(0)
