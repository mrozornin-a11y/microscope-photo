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


class NumberPad(QWidget):
    """Кнопки номера фотографии: 1…N и плитки «＋5» / «−5» для изменения числа кнопок."""

    numberClicked = Signal(int)
    countChanged = Signal(int)

    COLUMNS = 5
    STEP = 5
    MIN_COUNT = 20

    def __init__(self, count: int = 20, parent=None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(5)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[int, QPushButton] = {}
        self._value: int | None = None
        self._count = 0
        self._more = self._tile("＋5", "Добавить еще 5 кнопок номера", lambda: self.set_count(self._count + self.STEP))
        self._less = self._tile("−5", "Убрать последние 5 кнопок номера",
                                lambda: self.set_count(self._count - self.STEP))
        self.set_count(count, emit=False)

    def _tile(self, text: str, tip: str, fn) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("NumTile")
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(fn)
        return b

    def count(self) -> int:
        return self._count

    def set_count(self, count: int, emit: bool = True) -> None:
        count = max(self.MIN_COUNT, int(count))
        count = ((count + self.STEP - 1) // self.STEP) * self.STEP
        if count == self._count:
            return
        for n in range(self._count + 1, count + 1):          # добавить недостающие
            b = QPushButton(str(n))
            b.setObjectName("NumButton")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=n: self.numberClicked.emit(k))
            self._group.addButton(b)
            self._buttons[n] = b
        for n in range(count + 1, self._count + 1):          # убрать лишние
            b = self._buttons.pop(n)
            self._group.removeButton(b)
            b.deleteLater()
        self._count = count
        self._relayout()
        self._check()
        if emit:
            self.countChanged.emit(count)

    def _relayout(self) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        cols = self.COLUMNS
        for n in range(1, self._count + 1):
            self._grid.addWidget(self._buttons[n], (n - 1) // cols, (n - 1) % cols)
        row = (self._count + cols - 1) // cols
        self._grid.addWidget(self._more, row, 0)
        self._less.setVisible(self._count > self.MIN_COUNT)
        if self._count > self.MIN_COUNT:
            self._grid.addWidget(self._less, row, 1)

    AUTO_EXTEND_MAX = 100

    def set_value(self, n: int | None) -> None:
        """Отметить номер; если он больше числа кнопок — панель расширяется."""
        self._value = n
        if n is not None and self._count < n <= self.AUTO_EXTEND_MAX:
            self.set_count(n)
        self._check()

    def _check(self) -> None:
        n = self._value
        self._group.setExclusive(False)
        for k, b in self._buttons.items():
            b.setChecked(k == n)
        self._group.setExclusive(True)

    def value(self) -> int | None:
        return self._value

    def button(self, n: int) -> QPushButton:
        return self._buttons[n]
