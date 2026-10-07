"""Небольшие диалоги: «Применить дальше…», продолжение работы."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox,
                               QRadioButton, QVBoxLayout, QWidget)


class _CountMixin:
    def _add_count(self, lay: QVBoxLayout, remaining: int) -> None:
        lay.addWidget(_section("Применить к:"))
        self._count_group = QButtonGroup(self)
        self._counts: list[tuple[QRadioButton, int | None]] = []
        for text, n in (("следующим 5 фотографиям", 5), ("следующим 10 фотографиям", 10),
                        (f"всем оставшимся ({remaining})", None)):
            rb = QRadioButton(text)
            self._count_group.addButton(rb)
            self._counts.append((rb, n))
            lay.addWidget(rb)
        self._counts[0][0].setChecked(True)

    def count(self) -> int | None:
        for rb, n in self._counts:
            if rb.isChecked():
                return n
        return 5


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-weight: 600; margin-top: 6px;")
    return lbl


class ApplyParamsDialog(QDialog, _CountMixin):
    def __init__(self, remaining: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Применить дальше")
        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        self._add_count(lay, remaining)
        lay.addWidget(_section("Что копировать:"))
        self.name_cb = QCheckBox("Название шлифа")
        self.light_cb = QCheckBox("Освещение")
        self.mag_cb = QCheckBox("Увеличение")
        for cb in (self.name_cb, self.light_cb, self.mag_cb):
            cb.setChecked(True)
            lay.addWidget(cb)
        self.renumber_cb = QCheckBox("Номера — по порядку, начиная со следующего")
        self.renumber_cb.setChecked(True)
        lay.addSpacing(4)
        lay.addWidget(self.renumber_cb)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addSpacing(8)
        lay.addWidget(bb)


class ApplyCircleDialog(QDialog, _CountMixin):
    def __init__(self, remaining: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Применить круг дальше")
        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        info = QLabel("Тот же круг будет использован для следующих фотографий.\n"
                      "Удобно, если телефон не сдвигался во время серии.")
        info.setObjectName("Muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        self._add_count(lay, remaining)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addSpacing(8)
        lay.addWidget(bb)


def ask_continue(parent: QWidget, folder: str, done: int, total: int) -> bool | None:
    """True — продолжить, False — начать заново, None — закрыли окно."""
    box = QMessageBox(parent)
    box.setWindowTitle("Продолжить работу?")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText("Продолжить предыдущую работу?")
    box.setInformativeText(f"{folder}\n\nРазмечено фотографий: {done} из {total}")
    cont = box.addButton("Продолжить", QMessageBox.ButtonRole.AcceptRole)
    new = box.addButton("Начать заново", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(cont)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.exec()
    clicked = box.clickedButton()
    if clicked is cont:
        return True
    if clicked is new:
        return False
    return None
