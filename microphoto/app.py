"""Запуск приложения: логирование, перехват ошибок, главное окно."""

from __future__ import annotations

import logging
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler

from . import APP_NAME, APP_TITLE, __version__
from .core.paths import logs_dir

log = logging.getLogger("microphoto")


def setup_logging() -> str:
    path = logs_dir() / "microphoto.log"
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    return str(path)


def _install_excepthook() -> None:
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Необработанная ошибка:\n%s", text)
        try:
            crash = logs_dir() / f"error_{datetime.now():%Y%m%d_%H%M%S}.txt"
            crash.write_text(text, "utf-8")
        except Exception:
            crash = None
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                QMessageBox.warning(
                    None, APP_TITLE,
                    "Произошла непредвиденная ошибка. Работа сохранена, можно продолжать.\n\n"
                    f"{exc}\n\nПодробности записаны в папку журналов:\n{logs_dir()}")
        except Exception:
            pass

    sys.excepthook = hook


def main() -> int:
    setup_logging()
    log.info("Запуск %s %s", APP_NAME, __version__)
    _install_excepthook()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    app.setOrganizationName(APP_NAME)

    from .gui.theme import apply_theme
    from .gui.main_window import MainWindow

    apply_theme(app)
    win = MainWindow()
    win.show()
    code = app.exec()
    log.info("Завершение, код %s", code)
    return code
