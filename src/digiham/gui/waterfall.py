"""Spectrum + scrolling waterfall display.

Receives FFT magnitude columns from the engine and shows a live spectrum
strip above a colour waterfall. Click to place the Rx cursor; shift/right
click to place the Tx cursor. An embedded control strip lets you flip
through colour palettes and nudge the gain live, without opening Settings.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QWidget

from .theme import PALETTE

COLORMAP_NAMES = ["blue", "afmhot", "grey", "green", "viridis", "inferno", "ocean"]

# Occupied bandwidth of each mode's tone set, in Hz — sizes the Rx/Tx
# passband indicators on the waterfall (WSJT-X style shaded band rather
# than a bare line).
BANDWIDTH_HZ = {"FT8": 50.0, "FT4": 83.3, "WSPR": 6.0}
_DEFAULT_BANDWIDTH_HZ = 50.0


def _ramp(stops: list[tuple[float, int, int, int]]) -> np.ndarray:
    """Interpolate (pos 0..1, r, g, b) stops into a 256-entry uint8 LUT."""
    pos = [s[0] for s in stops]
    x = np.linspace(0.0, 1.0, 256)
    chans = [np.interp(x, pos, [s[i] for s in stops]) for i in (1, 2, 3)]
    return np.stack(chans, axis=1).astype(np.uint8)


def _make_colormap(name: str) -> np.ndarray:
    """Return a (256, 3) uint8 lookup table."""
    x = np.linspace(0.0, 1.0, 256)
    if name == "grey":
        rgb = np.stack([x, x, x], axis=1)
        return (rgb * 255).astype(np.uint8)
    if name == "afmhot":
        r = np.clip(x * 2.4, 0, 1)
        g = np.clip(x * 2.4 - 0.8, 0, 1)
        b = np.clip(x * 2.4 - 1.6, 0, 1)
        rgb = np.stack([r, g, b], axis=1)
        return (rgb * 255).astype(np.uint8)
    if name == "green":       # classic black -> green -> yellow -> white
        return _ramp([
            (0.00, 0, 0, 0),
            (0.35, 0, 70, 20),
            (0.60, 20, 180, 40),
            (0.85, 220, 230, 40),
            (1.00, 255, 255, 255),
        ])
    if name == "viridis":
        return _ramp([
            (0.00, 68, 1, 84),
            (0.25, 59, 82, 139),
            (0.50, 33, 145, 140),
            (0.75, 94, 201, 98),
            (1.00, 253, 231, 37),
        ])
    if name == "inferno":
        return _ramp([
            (0.00, 0, 0, 4),
            (0.25, 87, 16, 110),
            (0.50, 188, 55, 84),
            (0.75, 249, 142, 8),
            (1.00, 252, 255, 164),
        ])
    if name == "ocean":
        return _ramp([
            (0.00, 5, 10, 40),
            (0.33, 0, 90, 120),
            (0.66, 0, 190, 190),
            (1.00, 255, 255, 255),
        ])
    # "blue" (default) — dark navy -> cyan -> white
    r = np.clip(x * 1.6 - 0.6, 0, 1)
    g = np.clip(x * 1.4 - 0.1, 0, 1)
    b = np.clip(0.25 + x * 1.2, 0, 1)
    rgb = np.stack([r, g, b], axis=1)
    return (rgb * 255).astype(np.uint8)


class Waterfall(QWidget):
    rxClicked = Signal(int)               # Hz
    txClicked = Signal(int)               # Hz
    paletteChanged = Signal(str, float)   # colormap name, gain (live control edits)

    CTRL_H = 26                  # embedded colour/gain control strip
    SPEC_H = 64                  # spectrum strip height
    AXIS_H = 18                  # frequency axis height

    def __init__(self, fmax: int = 3600, parent=None):
        super().__init__(parent)
        self.fmax = fmax
        self.setMinimumHeight(180 + self.CTRL_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._cmap_name = "blue"
        self._cmap = _make_colormap(self._cmap_name)
        self._gain = 1.0
        self._zero = 0.0
        self._rx = 1500
        self._tx = 1500
        self._bw_hz = BANDWIDTH_HZ["FT8"]
        self._occupied: list[float] = []
        self._wf: np.ndarray | None = None      # (rows, W, 3) uint8
        self._spec_disp = np.zeros(1)           # last normalised row for the curve

        self._build_controls()

    # -- embedded quick controls ------------------------------------------

    def _build_controls(self) -> None:
        bar = QWidget(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(6)

        lay.addWidget(QLabel("Colour"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.addItems(COLORMAP_NAMES)
        self._cmap_combo.setCurrentText(self._cmap_name)
        self._cmap_combo.currentTextChanged.connect(self._on_cmap_chosen)
        lay.addWidget(self._cmap_combo)

        lay.addWidget(QLabel("Gain"))
        self._gain_slider = QSlider(Qt.Orientation.Horizontal)
        self._gain_slider.setRange(2, 50)      # gain 0.2 .. 5.0, in 0.1 steps
        self._gain_slider.setValue(int(round(self._gain * 10)))
        self._gain_slider.setFixedWidth(90)
        self._gain_slider.valueChanged.connect(self._on_gain_slider)
        lay.addWidget(self._gain_slider)

        self._gain_label = QLabel(f"{self._gain:.1f}x")
        self._gain_label.setFixedWidth(32)
        lay.addWidget(self._gain_label)
        lay.addStretch(1)

        self._ctrl_bar = bar
        self._style_ctrl_bar()

    def _style_ctrl_bar(self) -> None:
        # Read from the live PALETTE so refresh_theme() can restyle in place.
        self._ctrl_bar.setStyleSheet(
            f"background: {PALETTE['bg_alt']}; "
            f"border-bottom: 1px solid {PALETTE['border']};")

    def refresh_theme(self) -> None:
        """Re-apply theme colours after a live theme switch: the control bar's
        stylesheet is set once, and everything painted in paintEvent needs a
        repaint to pick up the new PALETTE."""
        self._style_ctrl_bar()
        self.update()

    def _on_cmap_chosen(self, name: str) -> None:
        self._cmap_name = name
        self._cmap = _make_colormap(name)
        self.update()
        self.paletteChanged.emit(self._cmap_name, self._gain)

    def _on_gain_slider(self, value: int) -> None:
        self._gain = value / 10.0
        self._gain_label.setText(f"{self._gain:.1f}x")
        self.update()
        self.paletteChanged.emit(self._cmap_name, self._gain)

    def resizeEvent(self, ev) -> None:
        self._ctrl_bar.setGeometry(0, 0, self.width(), self.CTRL_H)
        super().resizeEvent(ev)

    # -- configuration ---------------------------------------------------

    def set_palette(self, name: str, gain: float, zero: float) -> None:
        self._cmap_name = name
        self._cmap = _make_colormap(name)
        self._gain = max(0.2, gain)
        self._zero = zero

        self._cmap_combo.blockSignals(True)
        self._cmap_combo.setCurrentText(name)
        self._cmap_combo.blockSignals(False)
        self._gain_slider.blockSignals(True)
        self._gain_slider.setValue(int(round(self._gain * 10)))
        self._gain_slider.blockSignals(False)
        self._gain_label.setText(f"{self._gain:.1f}x")
        self.update()

    def set_mode(self, mode: str) -> None:
        self._bw_hz = BANDWIDTH_HZ.get(mode, _DEFAULT_BANDWIDTH_HZ)
        self.update()

    def set_markers(self, rx: int, tx: int) -> None:
        self._rx, self._tx = int(rx), int(tx)
        self.update()

    def set_occupied(self, freqs: list[float]) -> None:
        self._occupied = freqs
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
        return max(1, self.height() - self.CTRL_H - self.SPEC_H - self.AXIS_H)

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
        spec_top = self.CTRL_H
        spec_bottom = self.CTRL_H + self.SPEC_H
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
            fill = QColor(PALETTE["cyan"])
            fill.setAlpha(60)
            p.setBrush(fill)
            p.drawPolygon(poly)

        # waterfall
        if self._wf is not None:
            rows, ww, _ = self._wf.shape
            img = QImage(self._wf.tobytes(), ww, rows, ww * 3,
                         QImage.Format.Format_RGB888)
            p.drawImage(self.rect().adjusted(0, spec_bottom, 0, -self.AXIS_H), img)

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

        # cursors — a shaded passband like WSJT-X, not just a bare line
        self._draw_cursor(p, self._rx, PALETTE["green"], "Rx", spec_top)
        self._draw_cursor(p, self._tx, PALETTE["red"], "Tx", spec_top)
        self._draw_occupied(p, spec_top)
        p.end()

    def _draw_cursor(self, p: QPainter, hz: int, color: str, label: str, top: int) -> None:
        bottom = self.height() - self.AXIS_H
        half_px = (self._bw_hz / 2.0) / self.fmax * self.width()
        center_x = self._x_for_hz(hz)
        left_x = center_x - half_px
        right_x = center_x + half_px

        fill = QColor(color)
        fill.setAlpha(40)
        p.fillRect(QRectF(left_x, top, right_x - left_x, bottom - top), fill)

        edge_pen = QPen(QColor(color), 1)
        edge_pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(edge_pen)
        p.drawLine(int(left_x), top, int(left_x), bottom)
        p.drawLine(int(right_x), top, int(right_x), bottom)

        center_pen = QPen(QColor(color), 1)
        center_pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(center_pen)
        p.drawLine(int(center_x), top, int(center_x), bottom)

        p.setPen(QColor(color))
        p.drawText(int(left_x) + 3, top + 12, label)

    def _draw_occupied(self, p: QPainter, top: int) -> None:
        if not self._occupied:
            return
        bottom = self.height() - self.AXIS_H
        half_px = (self._bw_hz / 2.0) / self.fmax * self.width()
        color = QColor(PALETTE.get("amber", "#ff9800"))
        color.setAlpha(20)
        pen = QPen(QColor(PALETTE.get("amber", "#ff9800")), 1)
        pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(pen)
        for freq in self._occupied:
            cx = self._x_for_hz(freq)
            p.fillRect(QRectF(cx - half_px, top, 2 * half_px, bottom - top), color)

    # -- interaction -----------------------------------------------------

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        hz = self._hz_for_x(ev.position().x())
        if ev.button() == Qt.MouseButton.RightButton or \
                ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.txClicked.emit(hz)
        else:
            self.rxClicked.emit(hz)
