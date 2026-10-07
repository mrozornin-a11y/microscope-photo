"""Кнопки-переключатели (выбран один вариант) и полоса этапов."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget


class ToggleGroup(QWidget):
    """Группа кнопок, из которых выбрана одна (или ни одной)."""

    valueChanged = Signal(str)

    def __init__(self, options: list[tuple[str, str]], columns: int = 0, parent=None) -> None:
        super().__init__(parent)
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        cols = columns or len(options)
        for i, (key, text) in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("Toggle")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.valueChanged.emit(k))
            self._group.addButton(b)
            self._buttons[key] = b
            lay.addWidget(b, i // cols, i % cols)

    def set_value(self, key: str | None) -> None:
        self._group.setExclusive(False)
        for k, b in self._buttons.items():
            b.setChecked(k == key)
        self._group.setExclusive(True)

    def value(self) -> str | None:
        for k, b in self._buttons.items():
            if b.isChecked():
                return k
        return None

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]


class StepBar(QWidget):
    """[1. Фотографии] → [2. Поле зрения] → [3. Готово]"""

    stepClicked = Signal(int)

    TITLES = ("1. Фотографии", "2. Поле зрения", "3. Готово")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._buttons: list[QPushButton] = []
        for i, title in enumerate(self.TITLES):
            if i:
                arrow = QLabel("→")
                arrow.setObjectName("StepArrow")
                lay.addWidget(arrow)
            b = QPushButton(title)
            b.setObjectName("Step")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=i: self._clicked(k))
            self._buttons.append(b)
            lay.addWidget(b)

    def _clicked(self, i: int) -> None:
        # кнопка не должна сама менять состояние — его задает окно
        self._buttons[i].setChecked(not self._buttons[i].isChecked())
        self.stepClicked.emit(i)

    def set_step(self, i: int) -> None:
        for k, b in enumerate(self._buttons):
            b.setChecked(k == i)
