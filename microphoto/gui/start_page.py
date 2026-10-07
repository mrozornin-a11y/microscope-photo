"""Стартовый экран: одно большое действие — выбрать папку."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.image_loader import HEIC_SUPPORTED


class StartPage(QWidget):
    chooseFolder = Signal()
    openRecent = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StartPage")
        lay = QVBoxLayout(self)
        lay.addStretch(2)
        title = QLabel("Подготовка микрофотографий")
        title.setObjectName("BigTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        sub = QLabel("Шлифы и аншлифы, снятые на телефон через микроскоп:\n"
                     "обрезка по полю зрения, масштабная шкала, понятные имена файлов.")
        sub.setObjectName("Muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(28)
        btn = QPushButton("Выбрать папку с фотографиями")
        btn.setObjectName("Huge")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.chooseFolder)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(10)
        self.recent_btn = QPushButton()
        self.recent_btn.setObjectName("Link")
        self.recent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recent_btn.clicked.connect(self.openRecent)
        self.recent_btn.setVisible(False)
        lay.addWidget(self.recent_btn, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(18)
        formats = "JPG, PNG, TIFF" + (", HEIC" if HEIC_SUPPORTED else "")
        fmt = QLabel(f"Поддерживаются: {formats}. Исходные файлы не изменяются.")
        fmt.setObjectName("Hint")
        fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(fmt)
        lay.addStretch(3)

    def set_recent(self, folder: str | None) -> None:
        if folder:
            self.recent_btn.setText(f"Продолжить: {folder}")
            self.recent_btn.setVisible(True)
        else:
            self.recent_btn.setVisible(False)
