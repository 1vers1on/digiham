"""digiham application entry point."""

from __future__ import annotations

import logging
import os
import signal
import sys


def _configure_logging() -> None:
    level_name = os.environ.get("DIGIHAM_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    from PySide6.QtWidgets import QApplication

    from . import config
    from .gui.mainwindow import MainWindow
    from .gui.theme import apply_theme

    _configure_logging()
    log = logging.getLogger(__name__)
    cfg = config.load()
    log.info("starting digiham")

    app = QApplication(sys.argv)
    app.setApplicationName("digiham")
    app.setOrganizationName("digiham")
    apply_theme(app, cfg.font_size, cfg.theme)

    # let Ctrl-C in a terminal close the app cleanly
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    win = MainWindow(cfg)
    win.show()
    exit_code = app.exec()
    log.info("exiting digiham with code %s", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
