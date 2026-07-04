"""Tabbed settings dialog: Station, Radio, Audio, Decoding, Behaviour, Colours."""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ..config import Config
from ..rigctl import normalize_mode
from .. import audio
from .waterfall import COLORMAP_NAMES
from .theme import available_themes, DEFAULT_THEME


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("digiham — Settings")
        self.setMinimumWidth(520)
        self.cfg = dataclasses.replace(cfg)   # edit a copy

        tabs = QTabWidget()
        tabs.addTab(self._station_tab(), "Station")
        tabs.addTab(self._radio_tab(), "Radio")
        tabs.addTab(self._audio_tab(), "Audio")
        tabs.addTab(self._decode_tab(), "Decoding")
        tabs.addTab(self._behaviour_tab(), "Behaviour")
        tabs.addTab(self._reporting_tab(), "Reporting")
        tabs.addTab(self._colour_tab(), "Colours")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    # -- tabs ------------------------------------------------------------

    def _station_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.e_call = QLineEdit(self.cfg.my_call)
        self.e_call.setPlaceholderText("e.g. K1ABC")
        self.e_grid = QLineEdit(self.cfg.my_grid)
        self.e_grid.setPlaceholderText("e.g. FN42")
        self.s_pwr = QSpinBox(); self.s_pwr.setRange(0, 60)
        self.s_pwr.setValue(self.cfg.tx_power_dbm)
        self.s_pwr.setSuffix(" dBm")
        f.addRow("My callsign", self.e_call)
        f.addRow("My grid (Maidenhead)", self.e_grid)
        f.addRow("Tx power", self.s_pwr)
        lbl = QLabel("Power in dBm (37 dBm = 5 W). Used for WSPR and the log.")
        lbl.setWordWrap(True)
        f.addRow(lbl)
        return w

    def _radio_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.c_rig = QCheckBox("Enable rig control (rigctld)")
        self.c_rig.setChecked(self.cfg.rig_enabled)
        self.e_host = QLineEdit(self.cfg.rig_host)
        self.s_port = QSpinBox(); self.s_port.setRange(1, 65535)
        self.s_port.setValue(self.cfg.rig_port)
        self.c_split = QCheckBox("Use split (Tx on VFO B)")
        self.c_split.setChecked(self.cfg.rig_split)
        self.cb_mode = QComboBox()
        # Hamlib mode names only — rigctld accepts anything else as "mode
        # none" and some rigs then jump to a random mode. PKTUSB is what
        # radios label DATA-U / DATA-USB.
        self.cb_mode.addItems(["PKTUSB", "USB", "PKTLSB", "LSB", "FM", ""])
        try:
            self.cb_mode.setCurrentText(normalize_mode(self.cfg.rig_mode))
        except ValueError:
            self.cb_mode.setCurrentText("PKTUSB")
        self.cb_ptt = QComboBox()
        self.cb_ptt.addItems(["rigctld", "vox", "none"])
        self.cb_ptt.setCurrentText(self.cfg.ptt_method)
        f.addRow(self.c_rig)
        f.addRow("rigctld host", self.e_host)
        f.addRow("rigctld port", self.s_port)
        f.addRow("Rig mode on connect", self.cb_mode)
        f.addRow("PTT method", self.cb_ptt)
        f.addRow(self.c_split)
        return w

    def _audio_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.cb_in = QComboBox()
        self.cb_in.addItem("(default)", "")
        for _i, name in audio.list_devices("in"):
            self.cb_in.addItem(name, name)
        self._select(self.cb_in, self.cfg.audio_in)
        self.cb_out = QComboBox()
        self.cb_out.addItem("(default)", "")
        for _i, name in audio.list_devices("out"):
            self.cb_out.addItem(name, name)
        self._select(self.cb_out, self.cfg.audio_out)
        self.s_ingain = QDoubleSpinBox(); self.s_ingain.setRange(0.1, 10.0)
        self.s_ingain.setSingleStep(0.1); self.s_ingain.setValue(self.cfg.audio_in_gain)
        self.s_txlvl = QDoubleSpinBox(); self.s_txlvl.setRange(0.0, 1.0)
        self.s_txlvl.setSingleStep(0.05); self.s_txlvl.setValue(self.cfg.tx_audio_level)
        f.addRow("Input device", self.cb_in)
        f.addRow("Output device", self.cb_out)
        f.addRow("Input gain", self.s_ingain)
        f.addRow("Tx audio level", self.s_txlvl)
        note = QLabel("Devices are opened at 12 kHz where supported, otherwise "
                      "captured at the nearest rate and resampled.")
        note.setWordWrap(True)
        f.addRow(note)
        return w

    def _decode_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.s_depth = QSpinBox(); self.s_depth.setRange(1, 3)
        self.s_depth.setValue(self.cfg.decode_depth)
        self.s_fmin = QSpinBox(); self.s_fmin.setRange(100, 4000)
        self.s_fmin.setValue(self.cfg.freq_min); self.s_fmin.setSuffix(" Hz")
        self.s_fmax = QSpinBox(); self.s_fmax.setRange(200, 4000)
        self.s_fmax.setValue(self.cfg.freq_max); self.s_fmax.setSuffix(" Hz")
        self.c_ap = QCheckBox("Use DX call for a-priori decoding (dig weak replies)")
        self.c_ap.setChecked(self.cfg.decode_dxcall_ap)
        f.addRow("Depth (1 fast … 3 deep)", self.s_depth)
        f.addRow("Search freq min", self.s_fmin)
        f.addRow("Search freq max", self.s_fmax)
        f.addRow(self.c_ap)
        return w

    def _behaviour_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.c_autoseq = QCheckBox("Auto-sequence QSOs")
        self.c_autoseq.setChecked(self.cfg.auto_seq)
        self.c_callfirst = QCheckBox("Call 1st (answer the first caller to my CQ)")
        self.c_callfirst.setChecked(self.cfg.call_first)
        self.c_autolog = QCheckBox("Log automatically on RR73/73")
        self.c_autolog.setChecked(self.cfg.auto_log)
        self.c_dcqsy = QCheckBox("Double-click a decode sets Rx frequency")
        self.c_dcqsy.setChecked(self.cfg.double_click_qsy)
        self.c_cqonly = QCheckBox("Band Activity shows CQ only")
        self.c_cqonly.setChecked(self.cfg.cq_only)
        self.c_hidework = QCheckBox("Band Activity hides stations worked before")
        self.c_hidework.setChecked(self.cfg.hide_worked)
        self.s_wd = QSpinBox(); self.s_wd.setRange(0, 60)
        self.s_wd.setValue(self.cfg.tx_watchdog_min); self.s_wd.setSuffix(" min")
        f.addRow(self.c_autoseq)
        f.addRow(self.c_callfirst)
        f.addRow(self.c_autolog)
        f.addRow(self.c_dcqsy)
        f.addRow(self.c_cqonly)
        f.addRow(self.c_hidework)
        f.addRow("Tx watchdog (0 = off)", self.s_wd)

        alerts = QGroupBox("Alerts")
        af = QFormLayout(alerts)
        self.c_sound = QCheckBox("Play a sound for the events below")
        self.c_sound.setChecked(self.cfg.sound_alerts)
        self.c_newdxcc = QCheckBox("Highlight / alert new DXCC entities")
        self.c_newdxcc.setChecked(self.cfg.alert_new_dxcc)
        self.c_newgrid = QCheckBox("Alert new grid squares")
        self.c_newgrid.setChecked(self.cfg.alert_new_grid)
        af.addRow(self.c_sound)
        af.addRow(self.c_newdxcc)
        af.addRow(self.c_newgrid)
        f.addRow(alerts)
        return w

    def _reporting_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.c_udp = QCheckBox("Broadcast WSJT-X UDP messages")
        self.c_udp.setChecked(self.cfg.udp_enabled)
        self.e_udp_host = QLineEdit(self.cfg.udp_host)
        self.e_udp_host.setPlaceholderText("127.0.0.1 or a multicast group")
        self.s_udp_port = QSpinBox(); self.s_udp_port.setRange(1, 65535)
        self.s_udp_port.setValue(self.cfg.udp_port)
        self.e_udp_id = QLineEdit(self.cfg.udp_id)
        self.e_udp_id.setPlaceholderText("digiham")
        self.c_alltxt = QCheckBox("Write an ALL.TXT spot log (WSJT-X style)")
        self.c_alltxt.setChecked(self.cfg.all_txt)
        f.addRow(self.c_udp)
        f.addRow("UDP server host", self.e_udp_host)
        f.addRow("UDP server port", self.s_udp_port)
        f.addRow("Instance id", self.e_udp_id)
        f.addRow(self.c_alltxt)
        note = QLabel("Sends the same UDP datagrams as WSJT-X so companions "
                      "like GridTracker and JTAlert can follow digiham. Point "
                      "them at this host/port (WSJT-X default is 2237).")
        note.setWordWrap(True)
        f.addRow(note)
        return w

    def _colour_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.cb_theme = QComboBox()
        theme_names = list(available_themes())
        self.cb_theme.addItems(theme_names)
        self.cb_theme.setCurrentText(
            self.cfg.theme if self.cfg.theme in theme_names else DEFAULT_THEME)
        self.cb_wf = QComboBox(); self.cb_wf.addItems(COLORMAP_NAMES)
        self.cb_wf.setCurrentText(self.cfg.waterfall_palette)
        self.s_wfg = QDoubleSpinBox(); self.s_wfg.setRange(0.2, 5.0)
        self.s_wfg.setSingleStep(0.1); self.s_wfg.setValue(self.cfg.waterfall_gain)
        self.s_wfz = QDoubleSpinBox(); self.s_wfz.setRange(-30.0, 30.0)
        self.s_wfz.setValue(self.cfg.waterfall_zero)
        self.s_font = QSpinBox(); self.s_font.setRange(8, 18)
        self.s_font.setValue(self.cfg.font_size)
        f.addRow("Theme", self.cb_theme)
        f.addRow("Waterfall palette", self.cb_wf)
        f.addRow("Waterfall gain", self.s_wfg)
        f.addRow("Waterfall zero (dB)", self.s_wfz)
        f.addRow("Font size (restart)", self.s_font)
        return w

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _select(cb: QComboBox, value: str) -> None:
        idx = cb.findData(value)
        if idx >= 0:
            cb.setCurrentIndex(idx)

    def _accept(self) -> None:
        c = self.cfg
        c.my_call = self.e_call.text().strip().upper()
        c.my_grid = self.e_grid.text().strip().upper()
        c.tx_power_dbm = self.s_pwr.value()
        c.rig_enabled = self.c_rig.isChecked()
        c.rig_host = self.e_host.text().strip() or "localhost"
        c.rig_port = self.s_port.value()
        c.rig_split = self.c_split.isChecked()
        c.rig_mode = self.cb_mode.currentText()
        c.ptt_method = self.cb_ptt.currentText()
        c.audio_in = self.cb_in.currentData() or ""
        c.audio_out = self.cb_out.currentData() or ""
        c.audio_in_gain = self.s_ingain.value()
        c.tx_audio_level = self.s_txlvl.value()
        c.decode_depth = self.s_depth.value()
        c.freq_min = self.s_fmin.value()
        c.freq_max = self.s_fmax.value()
        c.decode_dxcall_ap = self.c_ap.isChecked()
        c.auto_seq = self.c_autoseq.isChecked()
        c.call_first = self.c_callfirst.isChecked()
        c.auto_log = self.c_autolog.isChecked()
        c.double_click_qsy = self.c_dcqsy.isChecked()
        c.cq_only = self.c_cqonly.isChecked()
        c.hide_worked = self.c_hidework.isChecked()
        c.sound_alerts = self.c_sound.isChecked()
        c.alert_new_dxcc = self.c_newdxcc.isChecked()
        c.alert_new_grid = self.c_newgrid.isChecked()
        c.tx_watchdog_min = self.s_wd.value()
        c.udp_enabled = self.c_udp.isChecked()
        c.udp_host = self.e_udp_host.text().strip() or "127.0.0.1"
        c.udp_port = self.s_udp_port.value()
        c.udp_id = self.e_udp_id.text().strip() or "digiham"
        c.all_txt = self.c_alltxt.isChecked()
        c.theme = self.cb_theme.currentText()
        c.waterfall_palette = self.cb_wf.currentText()
        c.waterfall_gain = self.s_wfg.value()
        c.waterfall_zero = self.s_wfz.value()
        c.font_size = self.s_font.value()
        self.accept()

    def result_config(self) -> Config:
        return self.cfg
