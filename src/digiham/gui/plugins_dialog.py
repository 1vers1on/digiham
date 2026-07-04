"""Plugins manager dialog: list loaded plugins, reload, open the folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

_COLS = ["Plugin", "Version", "Author", "Description", "File", "Status"]


class PluginsDialog(QDialog):
    def __init__(self, engine, plugins_dir: Path, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.plugins_dir = Path(plugins_dir)
        self.setWindowTitle("digiham — Plugins")
        self.resize(680, 360)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.info = QLabel()
        self.info.setWordWrap(True)

        btn_reload = QPushButton("Reload")
        btn_reload.clicked.connect(self._reload)
        btn_folder = QPushButton("Open plugins folder…")
        btn_folder.clicked.connect(self._open_folder)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)

        bottom = QHBoxLayout()
        bottom.addWidget(btn_folder)
        bottom.addStretch(1)
        bottom.addWidget(btn_reload)
        bottom.addWidget(btn_close)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Plugins folder: {self.plugins_dir}"))
        lay.addWidget(self.table)
        lay.addWidget(self.info)
        lay.addLayout(bottom)
        self.refresh()

    def refresh(self) -> None:
        mgr = self.engine.plugins
        rows = mgr.describe()
        self.table.setRowCount(0)
        themed = []
        for p in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            status = "disabled" if p["disabled"] else "active"
            if p["errors"]:
                status += f" ({p['errors']} error{'s' if p['errors'] != 1 else ''})"
            if p.get("themes"):
                status += "  ·  +theme"
                themed.extend(p["themes"])
            cells = [p["name"], p["version"], p.get("author", ""),
                     p["description"], p["source"], status]
            for c, text in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(str(text)))
        n = len(rows)
        msg = f"{n} plugin{'s' if n != 1 else ''} loaded."
        if themed:
            msg += f"  Themes added: {', '.join(sorted(themed))}."
        if mgr.load_errors:
            msg += "  Load errors:\n" + "\n".join(
                f"  • {src}: {err}" for src, err in mgr.load_errors)
        if not mgr.loaded:
            msg = "Plugins are disabled in Settings."
        self.info.setText(msg)

    def _reload(self) -> None:
        self.engine.plugins.reload()
        self.refresh()

    def _open_folder(self) -> None:
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.plugins_dir)))
