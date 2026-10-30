"""Этап 2. Проверка имен: таблица «№ — исходное имя — новое имя — ошибка».

Ошибки (не заполнены параметры, совпадающие имена, недоступные файлы)
подсвечены. Двойной щелчок по строке возвращает к этой фотографии на
этапе «Фотографии», чтобы исправить.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.name_check import NameRow, check_names
from . import theme
from .controller import ProjectController
from .media import MediaService

ERROR_BG = QColor("#fdecec")
EXCLUDED_FG = QColor(theme.MUTED)
COLUMNS = ("№", "Исходное название", "Новое название", "Ошибка")


class NamesPage(QWidget):
    finished = Signal()                 # «Далее» — к полю зрения
    fixRequested = Signal(int)          # вернуться к фото на этапе «Фотографии»

    def __init__(self, ctrl: ProjectController, media: MediaService, parent=None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.media = media
        self._rows: list[NameRow] = []
        self._dirty = True
        self._syncing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("TopBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-size: 12pt; font-weight: 600;")
        bl.addWidget(self.summary)
        bl.addSpacing(16)
        self.only_errors = QCheckBox("Только с ошибками")
        self.only_errors.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.only_errors.toggled.connect(self._fill)
        bl.addWidget(self.only_errors)
        bl.addStretch(1)
        hint = QLabel("Двойной щелчок по строке — вернуться к фото и исправить")
        hint.setObjectName("Hint")
        bl.addWidget(hint)
        self.fix_btn = QPushButton("Исправить выбранное →")
        self.fix_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fix_btn.clicked.connect(self._fix_current)
        bl.addWidget(self.fix_btn)
        root.addWidget(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)      # стрелки и Enter обрабатывает окно
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._fix_row(r))
        self.table.itemSelectionChanged.connect(self._on_selection)
        root.addWidget(self.table, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.refresh)

        ctrl.projectLoaded.connect(self._mark_dirty)
        ctrl.photoListChanged.connect(self._mark_dirty)
        ctrl.photoChanged.connect(lambda _i: self._mark_dirty())
        ctrl.settingsChanged.connect(self._mark_dirty)
        ctrl.currentChanged.connect(self._select_current)
        media.failed.connect(lambda _i, _m: self._mark_dirty())

    # ---------------------------------------------------------- данные
    def _mark_dirty(self) -> None:
        self._dirty = True
        if self.isVisible():
            self._timer.start()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if self._dirty:
            self.refresh()

    def on_enter(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self._dirty = False
        unreadable = {i for i in range(len(self.ctrl.photos)) if self.media.error(i)}
        self._rows = check_names(self.ctrl.photos, self.ctrl.settings.export.format, unreadable)
        active = [r for r in self._rows if not r.excluded]
        bad = sum(1 for r in active if not r.ok)
        if bad:
            self.summary.setText(f"⚠ Ошибок: {bad} из {len(active)}")
            self.summary.setStyleSheet(f"font-size: 12pt; font-weight: 600; color: {theme.ERROR};")
        else:
            self.summary.setText(f"✓ Все имена в порядке ({len(active)} фото)")
            self.summary.setStyleSheet(f"font-size: 12pt; font-weight: 600; color: {theme.SUCCESS};")
        self._fill()

    def error_count(self) -> int:
        return sum(1 for r in self._rows if not r.excluded and not r.ok)

    def _fill(self) -> None:
        rows = [r for r in self._rows if not self.only_errors.isChecked() or (not r.ok and not r.excluded)]
        self._syncing = True
        self.table.setRowCount(len(rows))
        for t, r in enumerate(rows):
            if r.excluded:
                problem = "не обрабатывается"
            else:
                problem = "; ".join(r.problems)
            new_name = f"{r.folder}\\{r.new_name}" if r.new_name else "—"
            values = (str(r.index + 1), r.source_name, new_name, problem)
            for c, v in enumerate(values):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, r.index)
                if c == 0:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if r.excluded:
                    it.setForeground(QBrush(EXCLUDED_FG))
                elif not r.ok:
                    it.setBackground(QBrush(ERROR_BG))
                    if c == 3:
                        it.setForeground(QBrush(QColor(theme.ERROR)))
                if c == 2 and r.folder:
                    it.setToolTip(f"Папка: {r.folder}\nФайл: {r.new_name}")
                self.table.setItem(t, c, it)
        self._syncing = False
        self._select_current(self.ctrl.current_index)
        self.fix_btn.setEnabled(bool(rows))

    # ---------------------------------------------------------- выбор строк
    def _row_of(self, index: int) -> int | None:
        for t in range(self.table.rowCount()):
            it = self.table.item(t, 0)
            if it is not None and it.data(Qt.ItemDataRole.UserRole) == index:
                return t
        return None

    def _select_current(self, index: int) -> None:
        t = self._row_of(index)
        self._syncing = True
        if t is None:
            self.table.clearSelection()
        else:
            self.table.selectRow(t)
            self.table.scrollToItem(self.table.item(t, 0), QAbstractItemView.ScrollHint.EnsureVisible)
        self._syncing = False

    def _on_selection(self) -> None:
        if self._syncing:
            return
        rows = self.table.selectionModel().selectedRows()
        if rows:
            idx = self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
            if idx != self.ctrl.current_index:
                self.ctrl.set_current(idx)

    def _fix_row(self, t: int) -> None:
        it = self.table.item(t, 0)
        if it is not None:
            self.fixRequested.emit(it.data(Qt.ItemDataRole.UserRole))

    def _fix_current(self) -> None:
        t = self._row_of(self.ctrl.current_index)
        if t is None and self.table.rowCount():
            t = 0
        if t is not None:
            self._fix_row(t)

    # ---------------------------------------------------------- навигация
    def next_label(self) -> str:
        return "К полю зрения →"

    def accept(self) -> None:
        """Enter / «Далее»: к полю зрения (при ошибках — спросить)."""
        self.refresh()
        bad = self.error_count()
        if bad:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Есть ошибки в именах")
            box.setText(f"Ошибок в именах: {bad}.")
            box.setInformativeText("Фото с незаполненными параметрами не будут сохранены, "
                                   "совпадающие имена получат суффикс «__повтор».")
            fix = box.addButton("Исправить", QMessageBox.ButtonRole.RejectRole)
            box.addButton("Все равно дальше", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(fix)
            box.exec()
            self.window().activateWindow()      # чтобы Enter снова работал в главном окне
            if box.clickedButton() is fix:
                first = next(r for r in self._rows if not r.excluded and not r.ok)
                self.fixRequested.emit(first.index)
                return
        self.finished.emit()

    def go_next(self) -> None:
        self.ctrl.set_current(self.ctrl.current_index + 1)

    def go_prev(self) -> None:
        self.ctrl.set_current(self.ctrl.current_index - 1)

    def commit_pending(self) -> None:
        pass
