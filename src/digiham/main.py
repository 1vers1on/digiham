"""digiham application entry point."""

from __future__ import annotations

import signal
import sys


def main() -> None:
    from PySide6.QtWidgets import QApplication

    from . import config
    from .gui.mainwindow import MainWindow
    from .gui.theme import apply_theme

    cfg = config.load()

    app = QApplication(sys.argv)
    app.setApplicationName("digiham")
    app.setOrganizationName("digiham")
    apply_theme(app, cfg.font_size, cfg.theme)

    # let Ctrl-C in a terminal close the app cleanly
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    win = MainWindow(cfg)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
