"""Этап 1. Фотографии: название шлифа, освещение, увеличение, номер."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QCompleter, QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu,
                               QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..core import naming, project_ops
from ..core.constants import LIGHT_MODES, MAGNIFICATIONS
from ..core.name_list import load_names
from .controller import ProjectController
from .dialogs import ApplyParamsDialog
from .media import MediaService
from .widgets.image_viewer import ImageViewer
from .widgets.toggles import ToggleGroup


def section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("SectionTitle")
    return lbl


class PhotoPage(QWidget):
    finished = Signal()          # «Далее» на последней фотографии

    def __init__(self, ctrl: ProjectController, media: MediaService, parent=None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.media = media
        self._updating = False
        self._shown_index = -1

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.viewer = ImageViewer()
        root.addWidget(self.viewer, 1)

        side = QFrame()
        side.setObjectName("SidePanel")
        side.setFixedWidth(340)
        root.addWidget(side)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)

        # --- название
        lay.addWidget(section("Название шлифа / образца"))
        self.name_combo = QComboBox()
        self.name_combo.setObjectName("BigCombo")
        self.name_combo.setEditable(True)
        self.name_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.name_combo.setMaxVisibleItems(20)
        self.name_combo.lineEdit().setPlaceholderText("Например, Св-25-14")
        self.name_combo.lineEdit().setClearButtonEnabled(True)
        self._names_model = QStringListModel(self)
        self.name_combo.setModel(self._names_model)
        completer = QCompleter(self._names_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.name_combo.setCompleter(completer)
        self.name_combo.lineEdit().editingFinished.connect(self.commit_name)
        self.name_combo.activated.connect(lambda _i: self.commit_name())
        lay.addWidget(self.name_combo)
        load_btn = QPushButton("Загрузить список…")
        load_btn.setObjectName("Link")
        load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        load_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        load_btn.setToolTip("Список названий из TXT, CSV или XLSX (первый столбец)")
        load_btn.clicked.connect(self.load_name_list)
        lay.addWidget(load_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # --- освещение
        lay.addWidget(section("Освещение"))
        self.light = ToggleGroup([(m.key, m.title) for m in LIGHT_MODES], columns=1)
        self.light.valueChanged.connect(self._light_clicked)
        lay.addWidget(self.light)

        # --- увеличение
        lay.addSpacing(4)
        lay.addWidget(section("Увеличение"))
        self.mag = ToggleGroup([(m.key, m.title) for m in MAGNIFICATIONS])
        self.mag.valueChanged.connect(self._mag_clicked)
        lay.addWidget(self.mag)

        # --- номер
        lay.addSpacing(4)
        lay.addWidget(section("Номер фотографии"))
        self.number = QSpinBox()
        self.number.setObjectName("BigSpin")
        self.number.setRange(0, 99999)
        self.number.setSpecialValueText("—")
        self.number.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.number.valueChanged.connect(self._number_changed)
        lay.addWidget(self.number)

        # --- имя результата
        lay.addSpacing(8)
        lay.addWidget(section("Будет сохранено как"))
        self.out_name = QLabel()
        self.out_name.setObjectName("OutputName")
        self.out_name.setWordWrap(True)
        self.out_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.out_name)

        self.excluded_banner = QLabel("Это фото не будет обработано.")
        self.excluded_banner.setObjectName("Muted")
        self.excluded_banner.setWordWrap(True)
        lay.addWidget(self.excluded_banner)

        lay.addStretch(1)

        # --- дополнительно
        more_row = QHBoxLayout()
        self.apply_btn = QPushButton("Применить дальше…")
        self.apply_btn.setObjectName("Link")
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_btn.setToolTip("Скопировать параметры этого фото на следующие")
        self.apply_btn.clicked.connect(self.apply_forward)
        more_row.addWidget(self.apply_btn)
        more_row.addStretch(1)
        self.more_btn = QPushButton("Дополнительно ▾")
        self.more_btn.setObjectName("Link")
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.more_btn.clicked.connect(self._show_more)
        more_row.addWidget(self.more_btn)
        lay.addLayout(more_row)

        hint = QLabel("Enter — далее  ·  ← → — листать\n1 2 3 4 — увеличение  ·  колесо — масштаб")
        hint.setObjectName("Hint")
        lay.addWidget(hint)

        ctrl.projectLoaded.connect(self._on_project)
        ctrl.currentChanged.connect(lambda _i: self.refresh())
        ctrl.photoChanged.connect(self._on_photo_changed)
        ctrl.settingsChanged.connect(self._update_out_name)
        ctrl.nameListChanged.connect(self._refresh_names)
        media.previewReady.connect(self._on_preview_ready)

    # ---------------------------------------------------------- обновление
    def _on_project(self) -> None:
        self._refresh_names()
        self.refresh()

    def _refresh_names(self) -> None:
        names = list(self.ctrl.project.name_list)
        seen = {n.casefold() for n in names}
        for p in self.ctrl.photos:
            n = p.sample_name.strip()
            if n and n.casefold() not in seen:
                seen.add(n.casefold())
                names.append(n)
        self._updating = True
        text = self.name_combo.currentText()
        self._names_model.setStringList(names)
        self.name_combo.setCurrentIndex(-1)
        self.name_combo.setEditText(text)
        self._updating = False

    def _on_photo_changed(self, i: int) -> None:
        if i == self.ctrl.current_index:
            self.refresh(load_image=False)

    def _on_preview_ready(self, i: int) -> None:
        if i == self.ctrl.current_index and self.isVisible():
            self._load_image()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.refresh()

    def refresh(self, load_image: bool = True) -> None:
        p = self.ctrl.current
        if p is None:
            return
        if load_image and self.isVisible():
            self._load_image()
        self._updating = True
        try:
            same_photo = self._shown_index == self.ctrl.current_index
            typing = self.name_combo.lineEdit().hasFocus() and same_photo
            if self.name_combo.currentText() != p.sample_name and not typing:
                self.name_combo.setEditText(p.sample_name)
            self._shown_index = self.ctrl.current_index
            self.light.set_value(p.light_mode)
            self.mag.set_value(p.magnification)
            if not (self.number.hasFocus() and same_photo):
                self.number.setValue(p.photo_number or 0)
        finally:
            self._updating = False
        enabled = not p.excluded
        for w in (self.name_combo, self.light, self.mag, self.number, self.apply_btn):
            w.setEnabled(enabled)
        self.excluded_banner.setVisible(p.excluded)
        self._update_out_name()

    def _load_image(self) -> None:
        i = self.ctrl.current_index
        p = self.ctrl.current
        if p is None:
            return
        if p.missing:
            self.viewer.show_message("Файл не найден")
            return
        err = self.media.error(i)
        if err:
            self.viewer.show_message("Не удалось открыть файл")
            return
        pm = self.media.preview(i)
        self.viewer.set_image(pm, (p.width, p.height) if p.width else None)

    def _update_out_name(self) -> None:
        p = self.ctrl.current
        if p is None:
            return
        if p.excluded:
            self.out_name.setText("—")
            return
        name = naming.output_file_name(p, self.ctrl.settings.export.format)
        if name:
            self.out_name.setText(name)
            self.out_name.setStyleSheet("")
        else:
            missing = []
            if not p.sample_name.strip():
                missing.append("название")
            if p.light_mode is None:
                missing.append("освещение")
            if p.magnification is None:
                missing.append("увеличение")
            if p.photo_number is None:
                missing.append("номер")
            self.out_name.setText("Не задано: " + ", ".join(missing))
            self.out_name.setStyleSheet("color: #6b7280;")

    # ---------------------------------------------------------- изменения
    def commit_name(self) -> None:
        if self._updating or self.ctrl.current is None:
            return
        text = " ".join(self.name_combo.currentText().split())
        p = self.ctrl.current
        if text != p.sample_name:
            self.ctrl.edit(self.ctrl.current_index, {"sample_name": text}, "Название шлифа")
            self._refresh_names()

    def commit_number(self) -> None:
        if self.number.hasFocus():
            self.number.interpretText()

    def commit_pending(self) -> None:
        """Перед переходом к другой фотографии — зафиксировать то, что вводится."""
        self.commit_number()
        self.commit_name()

    def _light_clicked(self, key: str) -> None:
        self.commit_name()
        self.ctrl.edit(self.ctrl.current_index, {"light_mode": key}, "Освещение")
        self.refresh(load_image=False)

    def _mag_clicked(self, key: str) -> None:
        self.commit_name()
        self.ctrl.edit(self.ctrl.current_index, {"magnification": key}, "Увеличение")
        self.refresh(load_image=False)

    def set_magnification_by_number(self, n: int) -> None:
        p = self.ctrl.current
        if p is None or p.excluded or not (1 <= n <= len(MAGNIFICATIONS)):
            return
        self._mag_clicked(MAGNIFICATIONS[n - 1].key)

    def _number_changed(self, value: int) -> None:
        if self._updating or self.ctrl.current is None:
            return
        i = self.ctrl.current_index
        self.ctrl.edit(i, {"photo_number": value or None}, "Номер фотографии", merge_key=f"number:{i}")
        self._update_out_name()

    # ---------------------------------------------------------- навигация
    def next_label(self) -> str:
        i = self.ctrl.current_index
        if i >= len(self.ctrl.photos) - 1:
            return "К полю зрения →"
        return "Далее →"

    def go_next(self) -> None:
        self.viewer.setFocus()      # снять фокус с полей ввода до смены фото
        self.commit_pending()
        i = self.ctrl.current_index
        if i >= len(self.ctrl.photos) - 1:
            self.finished.emit()
            return
        self.ctrl.set_current(i + 1)
        self.ctrl.inherit_into(i + 1)

    def go_prev(self) -> None:
        self.viewer.setFocus()
        self.commit_pending()
        self.ctrl.set_current(self.ctrl.current_index - 1)

    def accept(self) -> None:
        """Enter."""
        self.go_next()

    # ---------------------------------------------------------- дополнительно
    def apply_forward(self) -> None:
        self.commit_pending()
        i = self.ctrl.current_index
        remaining = len(project_ops.following_active(self.ctrl.photos, i, None))
        if remaining == 0:
            QMessageBox.information(self, "Применить дальше", "Это последняя фотография.")
            return
        dlg = ApplyParamsDialog(remaining, self)
        if not dlg.exec():
            return
        changes = project_ops.apply_params_forward(
            self.ctrl.photos, i, dlg.count(), dlg.name_cb.isChecked(), dlg.light_cb.isChecked(),
            dlg.mag_cb.isChecked(), dlg.renumber_cb.isChecked())
        if self.ctrl.edit_many(changes, "Применить параметры дальше"):
            self.window().statusBar().showMessage(f"Параметры применены к {len(changes)} фото", 4000)

    def _show_more(self) -> None:
        p = self.ctrl.current
        if p is None:
            return
        menu = QMenu(self)
        act_ex = menu.addAction("Не обрабатывать это фото")
        act_ex.setCheckable(True)
        act_ex.setChecked(p.excluded)
        act_clear = menu.addAction("Очистить параметры этого фото")
        menu.addSeparator()
        act_list = menu.addAction("Загрузить список названий…")
        chosen = menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))
        i = self.ctrl.current_index
        if chosen is act_ex:
            self.ctrl.edit(i, {"excluded": not p.excluded},
                           "Вернуть фото" if p.excluded else "Не обрабатывать фото")
        elif chosen is act_clear:
            self.ctrl.edit(i, {"sample_name": "", "light_mode": None, "magnification": None,
                               "photo_number": None}, "Очистить параметры")
        elif chosen is act_list:
            self.load_name_list()

    def load_name_list(self) -> None:
        start = self.ctrl.app_settings.last_list_folder() or self.ctrl.project.source_dir
        path, _ = QFileDialog.getOpenFileName(self, "Список названий шлифов", start,
                                              "Списки (*.txt *.csv *.xlsx);;Все файлы (*)")
        if not path:
            return
        self.ctrl.app_settings.set_last_list_folder(str(Path(path).parent))
        try:
            names = load_names(path)
        except Exception as e:
            QMessageBox.warning(self, "Список названий", f"Не удалось прочитать файл:\n{e}")
            return
        if not names:
            QMessageBox.information(self, "Список названий", "В файле не найдено ни одного названия.")
            return
        merged = list(self.ctrl.project.name_list)
        seen = {n.casefold() for n in merged}
        added = 0
        for n in names:
            if n.casefold() not in seen:
                seen.add(n.casefold())
                merged.append(n)
                added += 1
        self.ctrl.set_name_list(merged)
        self.window().statusBar().showMessage(f"Загружено названий: {len(names)} (новых: {added})", 5000)
        self.name_combo.setFocus()
        self.name_combo.lineEdit().selectAll()
