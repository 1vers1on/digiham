"""The digiham main window."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QCheckBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from .. import bands
from ..config import Config
from ..engine import DecodeRow, RadioEngine, MODES
from .decode_table import DecodeTable
from .log_window import LogWindow
from .settings_dialog import SettingsDialog
from .theme import PALETTE, apply_theme
from .waterfall import Waterfall


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.engine = RadioEngine(cfg)
        self._updating = False
        self._log_window: LogWindow | None = None

        self.setWindowTitle("digiham")
        self.resize(1180, 780)

        self._build_menu()
        self._build_ui()
        self._build_shortcuts()
        self._wire_engine()
        self._apply_visual_config()

        self._clock = QTimer(self)
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start()

        self.engine.start()
        self.statusBar().showMessage("ready")
        if not cfg.my_call:
            QTimer.singleShot(300, self._first_run_hint)

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #

    def _build_menu(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("&File")
        act_export = QAction("Export ADIF…", self)
        act_export.triggered.connect(self._export_adif)
        act_log = QAction("View log…", self)
        act_log.triggered.connect(self._show_log)
        act_settings = QAction("Settings…", self)
        act_settings.setShortcut("F2")
        act_settings.triggered.connect(self._open_settings)
        act_quit = QAction("Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_export)
        m_file.addAction(act_log)
        m_file.addSeparator()
        m_file.addAction(act_settings)
        m_file.addSeparator()
        m_file.addAction(act_quit)

        m_mode = mb.addMenu("&Mode")
        for mode in MODES:
            a = QAction(mode, self, checkable=True)
            a.setChecked(mode == self.engine.mode)
            a.triggered.connect(lambda _c, mo=mode: self._set_mode(mo))
            m_mode.addAction(a)
        self._mode_actions = {a.text(): a for a in m_mode.actions()}

        m_help = mb.addMenu("&Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self._build_topbar())

        decode_split = QSplitter(Qt.Orientation.Horizontal)
        ba_box = self._titled("Band Activity")
        self.band_table = DecodeTable()
        ba_box.layout().addWidget(self.band_table)
        rx_box = self._titled("Rx Frequency")
        self.rx_table = DecodeTable()
        rx_box.layout().addWidget(self.rx_table)
        decode_split.addWidget(ba_box)
        decode_split.addWidget(rx_box)
        decode_split.setSizes([640, 360])
        left.addWidget(decode_split, 3)

        self.waterfall = Waterfall(fmax=3600)
        left.addWidget(self.waterfall, 2)

        left.addLayout(self._build_progress())

        root.addLayout(left, 1)
        root.addWidget(self._build_controls())

        self.band_table.activated.connect(self.engine.double_click_decode)
        self.rx_table.activated.connect(self.engine.double_click_decode)
        self.waterfall.rxClicked.connect(self.engine.set_rx_freq)
        self.waterfall.txClicked.connect(self.engine.set_tx_freq)
        self.waterfall.paletteChanged.connect(self._on_waterfall_palette)

    def _build_shortcuts(self) -> None:
        """WSJT-X-style keyboard shortcuts for the common operating actions."""
        def sc(seq: str, fn) -> None:
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)

        sc("Esc", self.engine.halt_tx)                       # stop everything
        sc("Ctrl+E", lambda: self.tx_btn.toggle())           # Enable Tx
        sc("Ctrl+T", lambda: self.tune_btn.toggle())         # Tune
        sc("Ctrl+R", self._call_cq)                          # call CQ
        sc("Ctrl+L", self.engine.log_current_qso)            # log current QSO
        sc("Alt+Up", lambda: self._nudge_rx(1))
        sc("Alt+Down", lambda: self._nudge_rx(-1))

    def _nudge_rx(self, direction: int) -> None:
        self.engine.set_rx_freq(self.engine.rx_freq + direction * 10)

    def _titled(self, title: str) -> QGroupBox:
        box = QGroupBox(title)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(6, 6, 6, 6)
        return box

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 0, 4, 0)

        self.dial_label = QLabel()
        self.dial_label.setObjectName("bigFreq")
        f = QFont("DejaVu Sans Mono"); f.setPointSize(20); f.setBold(True)
        self.dial_label.setFont(f)
        lay.addWidget(self.dial_label)

        lay.addSpacing(12)
        lay.addWidget(QLabel("Band"))
        self.band_combo = QComboBox()
        self.band_combo.addItems(bands.BAND_ORDER)
        self.band_combo.setCurrentText(self.engine.band)
        self.band_combo.currentTextChanged.connect(self.engine.set_band)
        lay.addWidget(self.band_combo)

        lay.addWidget(QLabel("Mode"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(MODES))
        self.mode_combo.setCurrentText(self.engine.mode)
        self.mode_combo.currentTextChanged.connect(self._set_mode)
        lay.addWidget(self.mode_combo)

        self.monitor_btn = QPushButton("Monitor")
        self.monitor_btn.setCheckable(True)
        self.monitor_btn.setChecked(True)
        self.monitor_btn.toggled.connect(self.engine.set_monitor)
        lay.addWidget(self.monitor_btn)

        self.rig_btn = QPushButton("Connect Rig")
        self.rig_btn.setCheckable(True)
        self.rig_btn.toggled.connect(self._toggle_rig)
        lay.addWidget(self.rig_btn)

        lay.addStretch(1)
        self.clock_label = QLabel("00:00:00")
        self.clock_label.setObjectName("clock")
        cf = QFont("DejaVu Sans Mono"); cf.setPointSize(18); cf.setBold(True)
        self.clock_label.setFont(cf)
        lay.addWidget(self.clock_label)
        return bar

    def _build_progress(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        self.cycle_bar = QProgressBar()
        self.cycle_bar.setRange(0, 100)
        self.cycle_bar.setFormat("%p%")
        lay.addWidget(self.cycle_bar, 4)
        lay.addWidget(QLabel("Rx"))
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setTextVisible(False)
        self.level_bar.setMaximumWidth(140)
        lay.addWidget(self.level_bar, 1)
        self.decode_dot = QLabel("●")
        self.decode_dot.setStyleSheet(f"color: {PALETTE['text_dim']};")
        lay.addWidget(self.decode_dot)
        return lay

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(360)
        lay = QVBoxLayout(panel)
        lay.setSpacing(8)
        lay.setContentsMargins(0, 0, 0, 0)

        # station
        st = QGroupBox("Station")
        g = QGridLayout(st)
        self.station_label = QLabel()
        self.station_label.setStyleSheet(f"color:{PALETTE['green']}; font-weight:600;")
        g.addWidget(self.station_label, 0, 0, 1, 2)
        lay.addWidget(st)

        # DX
        dx = QGroupBox("DX")
        g = QGridLayout(dx)
        g.addWidget(QLabel("Call"), 0, 0)
        self.dx_call = QLineEdit(); self.dx_call.setPlaceholderText("DX call")
        g.addWidget(self.dx_call, 0, 1)
        g.addWidget(QLabel("Grid"), 1, 0)
        self.dx_grid = QLineEdit(); self.dx_grid.setPlaceholderText("grid")
        g.addWidget(self.dx_grid, 1, 1)
        btn_set = QPushButton("Set DX")
        btn_set.clicked.connect(self._set_dx)
        g.addWidget(btn_set, 2, 0)
        btn_logqso = QPushButton("Log QSO")
        btn_logqso.clicked.connect(self.engine.log_current_qso)
        g.addWidget(btn_logqso, 2, 1)
        self.qso_status = QLabel("—")
        self.qso_status.setWordWrap(True)
        self.qso_status.setStyleSheet(f"color:{PALETTE['text_dim']};")
        g.addWidget(self.qso_status, 3, 0, 1, 2)
        lay.addWidget(dx)

        # frequencies
        fr = QGroupBox("Frequencies (audio Hz)")
        g = QGridLayout(fr)
        g.addWidget(QLabel("Rx"), 0, 0)
        self.rx_spin = QSpinBox(); self.rx_spin.setRange(200, 4000)
        self.rx_spin.setValue(self.engine.rx_freq)
        self.rx_spin.valueChanged.connect(self.engine.set_rx_freq)
        g.addWidget(self.rx_spin, 0, 1)
        g.addWidget(QLabel("Tx"), 1, 0)
        self.tx_spin = QSpinBox(); self.tx_spin.setRange(200, 4000)
        self.tx_spin.setValue(self.engine.tx_freq)
        self.tx_spin.valueChanged.connect(self.engine.set_tx_freq)
        g.addWidget(self.tx_spin, 1, 1)
        self.hold_chk = QCheckBox("Hold Tx Freq")
        self.hold_chk.setChecked(self.cfg.hold_tx_freq)
        self.hold_chk.toggled.connect(self._set_hold)
        g.addWidget(self.hold_chk, 2, 0)
        self.lock_chk = QCheckBox("Lock Tx=Rx")
        self.lock_chk.setChecked(self.cfg.lock_tx_rx)
        self.lock_chk.toggled.connect(self._set_lock)
        g.addWidget(self.lock_chk, 2, 1)
        lay.addWidget(fr)

        # tx messages
        tm = QGroupBox("Tx Messages")
        grid = QGridLayout(tm)
        grid.addWidget(QLabel("Next"), 0, 0)
        grid.addWidget(QLabel("Now"), 0, 1)
        grid.addWidget(QLabel("Message"), 0, 2)
        self.tx_radios: list[QRadioButton] = []
        self.tx_nowbtns: list[QPushButton] = []
        self.tx_edits: list[QLineEdit] = []
        self._radio_group = QButtonGroup(self)
        for i in range(6):
            rb = QRadioButton()
            self._radio_group.addButton(rb, i + 1)
            grid.addWidget(rb, i + 1, 0)
            nb = QPushButton(f"Tx{i+1}")
            nb.setMaximumWidth(48)
            nb.clicked.connect(lambda _c, idx=i + 1: self._tx_now(idx))
            grid.addWidget(nb, i + 1, 1)
            ed = QLineEdit()
            ed.editingFinished.connect(lambda idx=i + 1: self._edit_message(idx))
            grid.addWidget(ed, i + 1, 2)
            self.tx_radios.append(rb)
            self.tx_nowbtns.append(nb)
            self.tx_edits.append(ed)
        self._radio_group.idToggled.connect(self._radio_selected)
        lay.addWidget(tm)

        # rig meters (fed by rigctld polling)
        rm = QGroupBox("Rig")
        g = QGridLayout(rm)
        self.meter_labels: dict[str, QLabel] = {}
        self.meter_titles: list[QLabel] = []
        for col, (key, title) in enumerate(
                [("strength", "S-meter"), ("power_w", "Pwr"), ("swr", "SWR"),
                 ("alc", "ALC"), ("vd", "Vd")]):
            t = QLabel(title)
            t.setStyleSheet(f"color:{PALETTE['text_dim']};")
            self.meter_titles.append(t)
            v = QLabel("—")
            v.setStyleSheet("font-weight:600;")
            g.addWidget(t, 0, col, Qt.AlignmentFlag.AlignHCenter)
            g.addWidget(v, 1, col, Qt.AlignmentFlag.AlignHCenter)
            self.meter_labels[key] = v
        lay.addWidget(rm)

        # operating controls
        oc = QGroupBox("Controls")
        g = QGridLayout(oc)
        self.tx_btn = QPushButton("Enable Tx")
        self.tx_btn.setObjectName("txButton")
        self.tx_btn.setCheckable(True)
        self.tx_btn.toggled.connect(self.engine.enable_tx)
        g.addWidget(self.tx_btn, 0, 0)
        self.halt_btn = QPushButton("Halt Tx")
        self.halt_btn.clicked.connect(self.engine.halt_tx)
        g.addWidget(self.halt_btn, 0, 1)
        self.cq_btn = QPushButton("CQ")
        self.cq_btn.setObjectName("cqButton")
        self.cq_btn.clicked.connect(self._call_cq)
        g.addWidget(self.cq_btn, 1, 0)
        self.autoseq_chk = QCheckBox("Auto Seq")
        self.autoseq_chk.setChecked(self.cfg.auto_seq)
        self.autoseq_chk.toggled.connect(lambda v: self._set_cfg("auto_seq", v))
        g.addWidget(self.autoseq_chk, 1, 1)
        self.callfirst_chk = QCheckBox("Call 1st")
        self.callfirst_chk.setChecked(self.cfg.call_first)
        self.callfirst_chk.toggled.connect(lambda v: self._set_cfg("call_first", v))
        g.addWidget(self.callfirst_chk, 2, 0)
        self.txodd_chk = QCheckBox("Tx Odd/2nd")
        self.txodd_chk.setChecked(self.cfg.tx_odd)
        self.txodd_chk.toggled.connect(self.engine.set_tx_odd)
        g.addWidget(self.txodd_chk, 2, 1)
        self.tune_btn = QPushButton("Tune")
        self.tune_btn.setObjectName("txButton")
        self.tune_btn.setCheckable(True)
        self.tune_btn.setToolTip("Transmit a steady carrier for ATU / amp tuning")
        self.tune_btn.toggled.connect(self._toggle_tune)
        g.addWidget(self.tune_btn, 3, 0)
        self.hidework_chk = QCheckBox("Hide B4")
        self.hidework_chk.setToolTip("Hide stations already worked from Band Activity")
        self.hidework_chk.setChecked(self.cfg.hide_worked)
        self.hidework_chk.toggled.connect(lambda v: self._set_cfg("hide_worked", v))
        g.addWidget(self.hidework_chk, 3, 1)
        lay.addWidget(oc)

        # free text
        ft = QGroupBox("Free text → Tx5")
        g = QHBoxLayout(ft)
        self.free_edit = QLineEdit()
        self.free_edit.setMaxLength(13)
        self.free_edit.setPlaceholderText("TNX 73 GL")
        self.free_edit.returnPressed.connect(self._send_free)
        g.addWidget(self.free_edit)
        lay.addWidget(ft)

        lay.addStretch(1)
        return panel

    # ------------------------------------------------------------------ #
    # engine wiring
    # ------------------------------------------------------------------ #

    def _wire_engine(self) -> None:
        e = self.engine
        e.decodesReady.connect(self._on_decodes)
        e.newCycle.connect(self._on_new_cycle)
        e.cycleTick.connect(self._on_cycle_tick)
        e.spectrum.connect(self.waterfall.push_spectrum)
        e.decoderBusy.connect(self._on_busy)
        e.audioLevel.connect(self._on_level)
        e.statusMessage.connect(lambda m: self.statusBar().showMessage(m, 6000))
        e.txStateChanged.connect(self._on_tx_state)
        e.txEnableChanged.connect(self._on_tx_enable)
        e.txMessagesChanged.connect(self._on_tx_messages)
        e.sequencerState.connect(self._on_seq_state)
        e.freqChanged.connect(self._on_freq)
        e.dialChanged.connect(self._on_dial)
        e.rigState.connect(self._on_rig_state)
        e.rigMeters.connect(self._on_rig_meters)
        e.bandChanged.connect(self._on_band_followed)
        e.qsoLogged.connect(self._on_qso_logged)

    def _apply_theme_colors(self) -> None:
        """Re-apply colours to the few widgets styled once at construction so a
        live theme switch reaches them too (chrome/tables/waterfall repaint on
        their own from the shared PALETTE)."""
        self.station_label.setStyleSheet(
            f"color:{PALETTE['green']}; font-weight:600;")
        self.qso_status.setStyleSheet(f"color:{PALETTE['text_dim']};")
        self.decode_dot.setStyleSheet(f"color: {PALETTE['text_dim']};")
        for t in self.meter_titles:
            t.setStyleSheet(f"color:{PALETTE['text_dim']};")
        self.waterfall.refresh_theme()

    def _apply_visual_config(self) -> None:
        self.station_label.setText(
            f"{self.cfg.my_call or '(no call)'}   {self.cfg.my_grid}")
        self.waterfall.set_palette(self.cfg.waterfall_palette,
                                   self.cfg.waterfall_gain, self.cfg.waterfall_zero)
        self.waterfall.set_mode(self.engine.mode)
        self.waterfall.set_markers(self.engine.rx_freq, self.engine.tx_freq)
        self._on_dial(self.engine.dial_hz)

    def _on_waterfall_palette(self, name: str, gain: float) -> None:
        self.cfg.waterfall_palette = name
        self.cfg.waterfall_gain = gain

    # ------------------------------------------------------------------ #
    # slots: decodes / activity
    # ------------------------------------------------------------------ #

    def _on_decodes(self, rows: list[DecodeRow]) -> None:
        for d in rows:
            if self.cfg.cq_only and not d.is_cq and not d.to_me:
                pass
            elif self.cfg.hide_worked and d.worked_before and not d.to_me \
                    and not d.new_dxcc:
                pass
            else:
                self.band_table.add_decode(d)
            if d.to_me or abs(d.freq_audio - self.engine.rx_freq) < 10 \
                    or (self.engine.seq.dxcall and d.de == self.engine.seq.dxcall):
                self.rx_table.add_decode(d)

    def _on_new_cycle(self, _cycle: int) -> None:
        self.band_table.mark_cycle()
        self.rx_table.mark_cycle()

    def _on_cycle_tick(self, frac: float, _cycle: int) -> None:
        self.cycle_bar.setValue(int(frac * 100))

    def _on_busy(self, busy: bool) -> None:
        color = PALETTE["amber"] if busy else PALETTE["text_dim"]
        self.decode_dot.setStyleSheet(f"color: {color};")

    def _on_level(self, level: float) -> None:
        self.level_bar.setValue(int(min(1.0, level * 4) * 100))

    # ------------------------------------------------------------------ #
    # slots: tx / sequencer
    # ------------------------------------------------------------------ #

    def _on_tx_state(self, txing: bool, msg: str) -> None:
        tuning = txing and msg == "TUNE"
        self._updating = True
        self.tune_btn.setChecked(tuning)
        self._updating = False
        if txing:
            label = "◉ TUNING" if tuning else f"◉ TRANSMITTING: {msg}"
            self.statusBar().showMessage(label)
            self.cycle_bar.setStyleSheet(
                f"QProgressBar::chunk{{background:{PALETTE['red']};}}")
        else:
            self.cycle_bar.setStyleSheet("")

    def _toggle_tune(self, on: bool) -> None:
        if self._updating:
            return
        self.engine.set_tune(on)

    def _on_tx_enable(self, on: bool) -> None:
        self._updating = True
        self.tx_btn.setChecked(on)
        self.tx_btn.setText("Tx ENABLED" if on else "Enable Tx")
        self._updating = False

    def _on_tx_messages(self, messages: list[str], next_idx: int) -> None:
        self._updating = True
        for i, msg in enumerate(messages):
            if self.tx_edits[i].text() != msg:
                self.tx_edits[i].setText(msg)
        btn = self._radio_group.button(next_idx)
        if btn:
            btn.setChecked(True)
        self._updating = False

    def _on_seq_state(self, s: dict) -> None:
        if s["dxcall"]:
            self.dx_call.setText(s["dxcall"])
            if s["dxgrid"]:
                self.dx_grid.setText(s["dxgrid"])
            rin = s["report_in"]
            txt = (f"{'CQ' if s['calling_cq'] else 'DX'} {s['dxcall']} "
                   f"{s['dxgrid']}  sent {s['report_out']:+d}"
                   + (f"  rcvd {rin:+d}" if rin is not None else ""))
            from .. import dxcc
            country = dxcc.country(s["dxcall"])
            if country:
                txt += f"\n{country}"
            if s["dxgrid"] and self.cfg.my_grid:
                from .. import geo
                db = geo.distance_bearing(self.cfg.my_grid, s["dxgrid"])
                if db is not None:
                    sep = "  ·  " if country else "\n"
                    txt += f"{sep}{db[0]:.0f} km @ {db[1]:.0f}°"
            self.qso_status.setText(txt)
        else:
            self.qso_status.setText("—")

    # ------------------------------------------------------------------ #
    # slots: frequency / rig
    # ------------------------------------------------------------------ #

    def _on_freq(self, rx: int, tx: int) -> None:
        self._updating = True
        self.rx_spin.setValue(rx)
        self.tx_spin.setValue(tx)
        self._updating = False
        self.waterfall.set_markers(rx, tx)

    def _on_dial(self, dial: float) -> None:
        mhz = dial / 1e6
        self.dial_label.setText(f"{mhz:10.6f}".strip() + " MHz")

    def _on_rig_state(self, connected: bool, dial: float, mode: str) -> None:
        self._updating = True
        self.rig_btn.setChecked(connected)
        self.rig_btn.setText("Rig ✓" if connected else "Connect Rig")
        self._updating = False
        if not connected:
            for lbl in self.meter_labels.values():
                lbl.setText("—")
                lbl.setStyleSheet("font-weight:600;")

    def _on_rig_meters(self, d: dict) -> None:
        if "strength" in d:
            v = d["strength"]
            # Hamlib STRENGTH is dB relative to S9 (6 dB per S-unit)
            self.meter_labels["strength"].setText(
                f"S9+{v:.0f}" if v > 0 else f"S{max(0.0, 9 + v / 6):.0f}")
        if "power_w" in d:
            self.meter_labels["power_w"].setText(f"{d['power_w']:.0f} W")
        if "swr" in d:
            swr = d["swr"]
            lbl = self.meter_labels["swr"]
            lbl.setText(f"{swr:.1f}" if swr >= 1.0 else "—")
            color = PALETTE["red"] if swr >= 2.5 else \
                PALETTE["amber"] if swr >= 1.8 else PALETTE["text"]
            lbl.setStyleSheet(f"font-weight:600; color:{color};")
        if "alc" in d:
            self.meter_labels["alc"].setText(f"{d['alc'] * 100:.0f}%")
        if "vd" in d:
            self.meter_labels["vd"].setText(f"{d['vd']:.1f} V")

    def _on_band_followed(self, band: str) -> None:
        self._updating = True
        self.band_combo.setCurrentText(band)
        self._updating = False

    def _on_qso_logged(self, q) -> None:
        self.statusBar().showMessage(f"logged {q.call}  {q.band} {q.mode}", 8000)
        if self._log_window is not None:
            self._log_window.add_qso(q)

    # ------------------------------------------------------------------ #
    # control handlers
    # ------------------------------------------------------------------ #

    def _tick_clock(self) -> None:
        self.clock_label.setText(
            dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S"))

    def _set_mode(self, mode: str) -> None:
        self.engine.set_mode(mode)
        self.waterfall.set_mode(mode)
        self._updating = True
        self.mode_combo.setCurrentText(mode)
        for name, act in self._mode_actions.items():
            act.setChecked(name == mode)
        self.band_combo.setCurrentText(self.engine.band)
        self._updating = False

    def _toggle_rig(self, on: bool) -> None:
        if self._updating:
            return
        if on:
            self.cfg.rig_enabled = True
            self.engine.connect_rig()
        else:
            self.engine.disconnect_rig()

    def _set_dx(self) -> None:
        self.engine.set_dx(self.dx_call.text().strip().upper(),
                           self.dx_grid.text().strip().upper())

    def _set_hold(self, on: bool) -> None:
        self.cfg.hold_tx_freq = on

    def _set_lock(self, on: bool) -> None:
        self.cfg.lock_tx_rx = on
        if on:
            self.engine.set_rx_freq(self.engine.rx_freq)

    def _tx_now(self, idx: int) -> None:
        self.engine.select_tx(idx)
        if not self.tx_btn.isChecked():
            self.tx_btn.setChecked(True)

    def _radio_selected(self, idx: int, checked: bool) -> None:
        if checked and not self._updating:
            self.engine.select_tx(idx)

    def _edit_message(self, idx: int) -> None:
        if self._updating:
            return
        self.engine.override_message(idx, self.tx_edits[idx - 1].text())

    def _call_cq(self) -> None:
        self.engine.start_cq()
        if not self.tx_btn.isChecked():
            self.tx_btn.setChecked(True)

    def _send_free(self) -> None:
        text = self.free_edit.text().strip()
        if text:
            self.engine.set_free_text(text)

    def _set_cfg(self, key: str, value) -> None:
        setattr(self.cfg, key, value)

    # ------------------------------------------------------------------ #
    # menu actions
    # ------------------------------------------------------------------ #

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            new = dlg.result_config()
            font_changed = new.font_size != self.cfg.font_size
            theme_changed = new.theme != self.cfg.theme
            audio_changed = (new.audio_in != self.cfg.audio_in
                             or new.audio_out != self.cfg.audio_out
                             or new.audio_in_gain != self.cfg.audio_in_gain)
            self.cfg = new
            new.save()
            self.engine.apply_config(new)
            self._apply_visual_config()
            self.autoseq_chk.setChecked(new.auto_seq)
            self.callfirst_chk.setChecked(new.call_first)
            self.hidework_chk.setChecked(new.hide_worked)
            if audio_changed:
                self.engine.restart_audio()
            if font_changed or theme_changed:
                apply_theme(self._app(), new.font_size, new.theme)
                self._apply_theme_colors()
            self.statusBar().showMessage("settings saved", 4000)

    @staticmethod
    def _app():
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()

    def _export_adif(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export ADIF", "digiham_export.adi", "ADIF (*.adi *.adif)")
        if path:
            n = self.engine.log.export(path)
            self.statusBar().showMessage(f"exported {n} QSOs → {path}", 6000)

    def _show_log(self) -> None:
        if self._log_window is None:
            self._log_window = LogWindow(self.engine.log, self)
        self._log_window.refresh()
        self._log_window.show()
        self._log_window.raise_()

    def _about(self) -> None:
        QMessageBox.about(
            self, "About digiham",
            "<h3>digiham</h3>"
            "<p>FT8 / FT4 / WSPR operating frontend with rig control, "
            "auto-sequencing, DXCC awareness and ADIF logging.</p>"
            "<p>Built on ft8lib, Hamlib rigctld and PySide6.</p>"
            "<p style='color:#888'><b>Shortcuts:</b> Esc halt · Ctrl+E enable Tx · "
            "Ctrl+T tune · Ctrl+R CQ · Ctrl+L log · Alt+↑/↓ nudge Rx</p>")

    def _first_run_hint(self) -> None:
        QMessageBox.information(
            self, "Set your callsign",
            "Set your callsign and grid in File → Settings (F2) before "
            "transmitting.")
        self._open_settings()

    # ------------------------------------------------------------------ #
    # shutdown
    # ------------------------------------------------------------------ #

    def closeEvent(self, ev) -> None:
        try:
            self.cfg.rx_freq = self.engine.rx_freq
            self.cfg.tx_freq = self.engine.tx_freq
            self.cfg.save()
        except Exception:
            pass
        self.engine.stop()
        super().closeEvent(ev)
