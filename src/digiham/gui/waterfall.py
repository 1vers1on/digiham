"""Spectrum + scrolling waterfall display.

Receives FFT magnitude columns from the engine and shows a live spectrum
strip above a colour waterfall. Click to place the Rx cursor; shift/right
click to place the Tx cursor.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QWidget

from .theme import PALETTE


def _make_colormap(name: str) -> np.ndarray:
    """Return a (256, 3) uint8 lookup table."""
    x = np.linspace(0.0, 1.0, 256)
    if name == "grey":
        rgb = np.stack([x, x, x], axis=1)
    elif name == "afmhot":
        r = np.clip(x * 2.4, 0, 1)
        g = np.clip(x * 2.4 - 0.8, 0, 1)
        b = np.clip(x * 2.4 - 1.6, 0, 1)
        rgb = np.stack([r, g, b], axis=1)
    else:  # "blue" — dark navy -> cyan -> white
        r = np.clip(x * 1.6 - 0.6, 0, 1)
        g = np.clip(x * 1.4 - 0.1, 0, 1)
        b = np.clip(0.25 + x * 1.2, 0, 1)
        rgb = np.stack([r, g, b], axis=1)
    return (rgb * 255).astype(np.uint8)


class Waterfall(QWidget):
    rxClicked = Signal(int)     # Hz
    txClicked = Signal(int)     # Hz

    SPEC_H = 64                 # spectrum strip height
    AXIS_H = 18                 # frequency axis height

    def __init__(self, fmax: int = 3600, parent=None):
        super().__init__(parent)
        self.fmax = fmax
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._cmap = _make_colormap("blue")
        self._gain = 1.0
        self._zero = 0.0
        self._rx = 1500
        self._tx = 1500
        self._wf: np.ndarray | None = None      # (rows, W, 3) uint8
        self._spec_disp = np.zeros(1)           # last normalised row for the curve

    # -- configuration ---------------------------------------------------

    def set_palette(self, name: str, gain: float, zero: float) -> None:
        self._cmap = _make_colormap(name)
        self._gain = max(0.2, gain)
        self._zero = zero
        self.update()

    def set_markers(self, rx: int, tx: int) -> None:
        self._rx, self._tx = int(rx), int(tx)
        self.update()

    # -- data ------------------------------------------------------------

    def push_spectrum(self, db: np.ndarray, bin_hz: float) -> None:
        w = max(1, self._wf_width())
        # map display columns -> FFT bins covering 0..fmax
        freqs = np.linspace(0, self.fmax, w)
        idx = np.clip((freqs / bin_hz).astype(int), 0, len(db) - 1)
        row_db = db[idx]
        base = np.percentile(row_db, 25) + self._zero
        span = 45.0 / self._gain
        norm = np.clip((row_db - base) / span, 0.0, 1.0)
        self._spec_disp = norm
        colors = self._cmap[(norm * 255).astype(np.uint8)]     # (w, 3)

        rows = self._wf_rows()
        if self._wf is None or self._wf.shape[1] != w or self._wf.shape[0] != rows:
            self._wf = np.zeros((rows, w, 3), dtype=np.uint8)
        self._wf = np.roll(self._wf, 1, axis=0)
        self._wf[0] = colors
        self.update()

    # -- geometry --------------------------------------------------------

    def _wf_width(self) -> int:
        return max(1, self.width())

    def _wf_rows(self) -> int:
        return max(1, self.height() - self.SPEC_H - self.AXIS_H)

    def _x_for_hz(self, hz: float) -> float:
        return hz / self.fmax * self.width()

    def _hz_for_x(self, x: float) -> int:
        return int(round(np.clip(x / max(1, self.width()) * self.fmax, 0, self.fmax)))

    # -- painting --------------------------------------------------------

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(PALETTE["bg_alt"]))

        # spectrum strip
        spec_bottom = self.SPEC_H
        if self._spec_disp.size > 1:
            n = self._spec_disp.size
            poly = QPolygonF()
            poly.append(QPointF(0, spec_bottom))
            for i in range(n):
                x = i / (n - 1) * w
                y = spec_bottom - self._spec_disp[i] * (self.SPEC_H - 4)
                poly.append(QPointF(x, y))
            poly.append(QPointF(w, spec_bottom))
            p.setPen(QPen(QColor(PALETTE["cyan"]), 1))
            p.setBrush(QColor(58, 208, 224, 60))
            p.drawPolygon(poly)

        # waterfall
        if self._wf is not None:
            rows, ww, _ = self._wf.shape
            img = QImage(self._wf.tobytes(), ww, rows, ww * 3,
                         QImage.Format.Format_RGB888)
            p.drawImage(self.rect().adjusted(0, self.SPEC_H, 0, -self.AXIS_H), img)

        # frequency axis
        axis_y = h - self.AXIS_H
        p.setPen(QColor(PALETTE["border"]))
        p.drawLine(0, axis_y, w, axis_y)
        p.setPen(QColor(PALETTE["text_dim"]))
        step = 500
        f = 0
        while f <= self.fmax:
            x = int(self._x_for_hz(f))
            p.drawLine(x, axis_y, x, axis_y + 4)
            if f % 1000 == 0:
                p.drawText(x + 2, h - 4, f"{f}")
            f += step

        # cursors
        self._draw_cursor(p, self._rx, PALETTE["green"], "Rx")
        self._draw_cursor(p, self._tx, PALETTE["red"], "Tx")
        p.end()

    def _draw_cursor(self, p: QPainter, hz: int, color: str, label: str) -> None:
        x = int(self._x_for_hz(hz))
        pen = QPen(QColor(color), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(x, self.SPEC_H, x, self.height() - self.AXIS_H)
        p.setPen(QColor(color))
        p.drawText(x + 3, self.SPEC_H + 12, label)

    # -- interaction -----------------------------------------------------

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        hz = self._hz_for_x(ev.position().x())
        if ev.button() == Qt.MouseButton.RightButton or \
                ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.txClicked.emit(hz)
        else:
            self.rxClicked.emit(hz)
