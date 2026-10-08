"""Этап 3. Готово: итоговый preview, экспорт, пересборка."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QMessageBox,
                               QProgressBar, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ..core import naming, project_ops
from ..core.constants import EXPORT_FORMATS
from ..core.models import BACKGROUND_COLORS
from ..core.exporter import plan_export
from ..workers.export_worker import ExportSummary, ExportWorker
from ..workers.render_worker import FinalRenderer
from .controller import ProjectController
from .media import MediaService
from .photo_page import section
from .widgets.image_viewer import ImageViewer
from .widgets.toggles import ToggleGroup

log = logging.getLogger(__name__)

DEFAULT_OUT_NAME = "готовые фотографии"


def _elide_path(p: str, n: int = 48) -> str:
    return p if len(p) <= n else "…" + p[-(n - 1):]


class FinalPage(QWidget):
    openSettings = Signal()
    gotoPhoto = Signal(int, int)        # индекс фото, этап
    startOver = Signal()
    busyChanged = Signal(bool)

    def __init__(self, ctrl: ProjectController, media: MediaService, parent=None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.media = media
        self.worker: ExportWorker | None = None
        self.last_summary: ExportSummary | None = None
        self.renderer = FinalRenderer(self)
        self.renderer.ready.connect(self._on_rendered)
        self.renderer.failed.connect(self._on_render_failed)
        self._mode = "result"
        self._render_pending = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("TopBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 6, 12, 6)
        self.mode_toggle = ToggleGroup([("source", "Исходное"), ("result", "Готовое")])
        self.mode_toggle.setFixedWidth(260)
        self.mode_toggle.set_value("result")
        self.mode_toggle.valueChanged.connect(self._set_mode)
        bl.addWidget(self.mode_toggle)
        bl.addStretch(1)
        self.render_lbl = QLabel()
        self.render_lbl.setObjectName("Muted")
        bl.addWidget(self.render_lbl)
        left.addWidget(bar)
        self.viewer = ImageViewer()
        left.addWidget(self.viewer, 1)
        root.addLayout(left, 1)

        side = QFrame()
        side.setObjectName("SidePanel")
        side.setFixedWidth(340)
        root.addWidget(side)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        self.side_stack = QStackedWidget()
        sl.addWidget(self.side_stack)
        self.side_stack.addWidget(self._build_ready())
        self.side_stack.addWidget(self._build_progress())
        self.side_stack.addWidget(self._build_done())

        ctrl.currentChanged.connect(lambda _i: self._refresh_if_visible())
        ctrl.photoChanged.connect(self._on_photo_changed)
        ctrl.settingsChanged.connect(self._on_settings_changed)
        ctrl.outputDirChanged.connect(self._update_ready)
        ctrl.projectLoaded.connect(self._on_project)
        media.previewReady.connect(self._on_preview_ready)

    # ---------------------------------------------------------- построение
    def _panel(self) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        return w, lay

    def _build_ready(self) -> QWidget:
        w, lay = self._panel()
        lay.addWidget(section("Проверка"))
        self.check_lbl = QLabel()
        self.check_lbl.setWordWrap(True)
        self.check_lbl.setStyleSheet("font-size: 11pt;")
        lay.addWidget(self.check_lbl)
        self.fix_btn = QPushButton()
        self.fix_btn.setObjectName("Link")
        self.fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fix_btn.clicked.connect(self._goto_problem)
        lay.addWidget(self.fix_btn, 0, Qt.AlignmentFlag.AlignLeft)

        lay.addSpacing(6)
        lay.addWidget(section("Это фото"))
        self.name_lbl = QLabel()
        self.name_lbl.setObjectName("OutputName")
        self.name_lbl.setWordWrap(True)
        lay.addWidget(self.name_lbl)
        self.scale_lbl = QLabel()
        self.scale_lbl.setObjectName("Muted")
        self.scale_lbl.setWordWrap(True)
        lay.addWidget(self.scale_lbl)

        lay.addSpacing(6)
        lay.addWidget(section("Папка результата"))
        self.out_lbl = QLabel()
        self.out_lbl.setWordWrap(True)
        lay.addWidget(self.out_lbl)
        out_btn = QPushButton("Выбрать папку результата…")
        out_btn.clicked.connect(self.choose_output)
        lay.addWidget(out_btn)

        lay.addSpacing(10)
        self.export_btn = QPushButton("Обработать и сохранить")
        self.export_btn.setObjectName("Primary")
        self.export_btn.setMinimumHeight(44)
        self.export_btn.clicked.connect(self.start_export)
        lay.addWidget(self.export_btn)
        self.export_info = QLabel()
        self.export_info.setObjectName("Hint")
        self.export_info.setWordWrap(True)
        lay.addWidget(self.export_info)

        lay.addStretch(1)
        self.more_btn = QPushButton("Дополнительно ▸")
        self.more_btn.setObjectName("Link")
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.clicked.connect(self._toggle_more)
        lay.addWidget(self.more_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.more = QFrame()
        ml = QVBoxLayout(self.more)
        ml.setContentsMargins(0, 0, 0, 0)
        bg_row = QHBoxLayout()
        bg_row.addWidget(QLabel("Фон:"))
        self.bg_toggle = ToggleGroup([(k, v) for k, v in BACKGROUND_COLORS.items()])
        self.bg_toggle.setToolTip("Цвет за пределами поля зрения (для всей партии)")
        self.bg_toggle.valueChanged.connect(self._background_changed)
        bg_row.addWidget(self.bg_toggle, 1)
        ml.addLayout(bg_row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Формат:"))
        self.format_combo = QComboBox()
        for key, (title, _ext) in EXPORT_FORMATS.items():
            self.format_combo.addItem(title, key)
        self.format_combo.currentIndexChanged.connect(self._format_changed)
        row.addWidget(self.format_combo, 1)
        ml.addLayout(row)
        row2 = QHBoxLayout()
        self.quality_lbl = QLabel("Качество JPEG:")
        row2.addWidget(self.quality_lbl)
        self.quality = QSpinBox()
        self.quality.setRange(50, 100)
        self.quality.valueChanged.connect(self._quality_changed)
        row2.addWidget(self.quality, 1)
        ml.addLayout(row2)
        settings_btn = QPushButton("⚙ Резкость и масштабная шкала…")
        settings_btn.setObjectName("Link")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self.openSettings)
        ml.addWidget(settings_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.more.setVisible(False)
        lay.addWidget(self.more)
        hint = QLabel("Колесо — масштаб · двойной щелчок — вписать")
        hint.setObjectName("Hint")
        lay.addWidget(hint)
        return w

    def _build_progress(self) -> QWidget:
        w, lay = self._panel()
        lay.addStretch(1)
        t = QLabel("Обработка фотографий…")
        t.setStyleSheet("font-size: 13pt; font-weight: 600;")
        lay.addWidget(t)
        self.prog_lbl = QLabel("0 / 0")
        self.prog_lbl.setStyleSheet("font-size: 12pt;")
        lay.addWidget(self.prog_lbl)
        self.prog = QProgressBar()
        self.prog.setTextVisible(False)
        lay.addWidget(self.prog)
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.cancel_export)
        lay.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignLeft)
        note = QLabel("Отмена сработает после завершения текущего файла.\nУже сохраненные файлы останутся.")
        note.setObjectName("Hint")
        lay.addWidget(note)
        lay.addStretch(2)
        return w

    def _build_done(self) -> QWidget:
        w, lay = self._panel()
        self.done_title = QLabel("Готово")
        self.done_title.setObjectName("BigTitle")
        lay.addWidget(self.done_title)
        self.done_lbl = QLabel()
        self.done_lbl.setStyleSheet("font-size: 11pt;")
        self.done_lbl.setWordWrap(True)
        lay.addWidget(self.done_lbl)
        err_row = QHBoxLayout()
        self.err_lbl = QLabel()
        self.err_lbl.setStyleSheet("font-size: 11pt;")
        err_row.addWidget(self.err_lbl)
        self.err_btn = QPushButton("Показать")
        self.err_btn.setObjectName("Link")
        self.err_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.err_btn.clicked.connect(self._toggle_errors)
        err_row.addWidget(self.err_btn)
        err_row.addStretch(1)
        lay.addLayout(err_row)
        self.err_list = QListWidget()
        self.err_list.setVisible(False)
        self.err_list.setMaximumHeight(180)
        self.err_list.itemDoubleClicked.connect(self._error_clicked)
        lay.addWidget(self.err_list)
        lay.addSpacing(8)
        lay.addWidget(section("Папка результата"))
        self.done_path = QLabel()
        self.done_path.setWordWrap(True)
        self.done_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.done_path)
        lay.addSpacing(8)
        open_btn = QPushButton("Открыть папку")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._open_output)
        lay.addWidget(open_btn)
        rebuild = QPushButton("Пересобрать")
        rebuild.setToolTip("Создать результат заново из оригиналов с текущими настройками.\n"
                           "Названия, увеличения и круги задавать заново не нужно.")
        rebuild.clicked.connect(self._back_to_ready)
        lay.addWidget(rebuild)
        again = QPushButton("Начать заново")
        again.clicked.connect(self.startOver)
        lay.addWidget(again)
        lay.addStretch(1)
        hint = QLabel("«Пересобрать»: измените резкость, шкалу или формат и снова "
                      "нажмите «Обработать и сохранить». Разметку задавать заново не нужно.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    # ---------------------------------------------------------- состояние
    def _on_project(self) -> None:
        self.side_stack.setCurrentIndex(0)
        self.last_summary = None
        self._sync_export_controls()

    def on_enter(self) -> None:
        if self.side_stack.currentIndex() == 2:
            self.side_stack.setCurrentIndex(0)
        self.refresh()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.refresh()

    def _refresh_if_visible(self) -> None:
        if self.isVisible():
            self.refresh()

    def _on_photo_changed(self, i: int) -> None:
        if not self.isVisible():
            return
        if i == self.ctrl.current_index:
            self.refresh()
        else:
            self._update_ready()

    def _on_settings_changed(self) -> None:
        self._sync_export_controls()
        if self.isVisible():
            self.refresh()

    def _on_preview_ready(self, i: int) -> None:
        if self.isVisible() and i == self.ctrl.current_index and self._mode == "source":
            self.refresh()

    def output_dir(self) -> str:
        if self.ctrl.project.output_dir:
            return self.ctrl.project.output_dir
        src = self.ctrl.project.source_dir
        return str(Path(src) / DEFAULT_OUT_NAME) if src else ""

    def refresh(self) -> None:
        self._update_ready()
        self._render_current()

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self.mode_toggle.set_value(mode)
        self._render_current()

    def toggle_mode(self) -> None:
        self._set_mode("source" if self._mode == "result" else "result")

    def _render_current(self) -> None:
        p = self.ctrl.current
        if p is None:
            return
        i = self.ctrl.current_index
        if p.missing:
            self.renderer.cancel()
            self.viewer.show_message("Файл не найден")
            self.render_lbl.setText("")
            return
        if self._mode == "source":
            self.renderer.cancel()
            self.viewer.set_image(self.media.preview(i), (p.width, p.height) if p.width else None)
            self.render_lbl.setText("")
            return
        if p.excluded:
            self.renderer.cancel()
            self.viewer.show_message("Это фото не будет обработано")
            self.render_lbl.setText("")
            return
        self.render_lbl.setText("Готовлю preview…")
        self.renderer.request(p, self.ctrl.settings)

    def _on_rendered(self, img) -> None:
        if self._mode != "result":
            return
        self.render_lbl.setText("")
        self.viewer.set_image(QPixmap.fromImage(img), (img.width(), img.height()), keep_view=True)

    def _on_render_failed(self, err: str) -> None:
        self.render_lbl.setText("")
        self.viewer.show_message(f"Не удалось подготовить preview:\n{err}")

    def _problems(self) -> tuple[list[int], list[int]]:
        photos = self.ctrl.photos
        incomplete = [i for i, p in enumerate(photos) if not p.excluded and not p.missing and not p.params_complete()]
        # файлы, которые не удалось открыть, проверить нельзя — они попадут в список ошибок
        unconfirmed = [i for i, p in enumerate(photos) if not p.excluded and not p.missing
                       and not p.circle_confirmed and not self.media.error(i)]
        return incomplete, unconfirmed

    def _update_ready(self) -> None:
        p = self.ctrl.current
        if p is None:
            return
        incomplete, unconfirmed = self._problems()
        if incomplete:
            self.check_lbl.setText(f"⚠ Не заполнены параметры: {len(incomplete)} фото")
            self.check_lbl.setStyleSheet("font-size: 11pt; color: #b45309;")
            self.fix_btn.setText("Перейти к первому →")
            self.fix_btn.setVisible(True)
        elif unconfirmed:
            self.check_lbl.setText(f"Не проверено кругов: {len(unconfirmed)}.\n"
                                   "Будут использованы найденные автоматически.")
            self.check_lbl.setStyleSheet("font-size: 11pt; color: #b45309;")
            self.fix_btn.setText("Проверить →")
            self.fix_btn.setVisible(True)
        else:
            self.check_lbl.setText("✓ Все фотографии проверены")
            self.check_lbl.setStyleSheet("font-size: 11pt; color: #15803d;")
            self.fix_btn.setVisible(False)

        fmt = self.ctrl.settings.export.format
        self.name_lbl.setText(naming.output_file_name(p, fmt) or "— параметры не заполнены —")
        sc = self.ctrl.settings.scale
        if p.excluded:
            self.scale_lbl.setText("Это фото не будет обработано")
        elif not sc.enabled:
            self.scale_lbl.setText("Масштабная шкала отключена")
        elif p.magnification and p.circle:
            cal = sc.calibration[p.magnification]
            self.scale_lbl.setText(f"Шкала: {cal.label}")
        else:
            self.scale_lbl.setText("")
        out = self.output_dir()
        self.out_lbl.setText(_elide_path(out))
        self.out_lbl.setToolTip(out)
        n = sum(1 for i, q in enumerate(self.ctrl.photos)
                if not q.excluded and not q.missing and q.params_complete() and not self.media.error(i))
        already = sum(1 for q in self.ctrl.photos if q.export_status == "done")
        self.export_btn.setText("Пересобрать результат" if already else "Обработать и сохранить")
        self.export_btn.setEnabled(n > 0 and self.worker is None)
        self.export_info.setText(f"Будет сохранено фотографий: {n}")

    def _goto_problem(self) -> None:
        incomplete, unconfirmed = self._problems()
        if incomplete:
            self.gotoPhoto.emit(incomplete[0], 0)
        elif unconfirmed:
            self.gotoPhoto.emit(unconfirmed[0], 1)

    def _toggle_more(self) -> None:
        vis = not self.more.isVisible()
        self.more.setVisible(vis)
        self.more_btn.setText("Дополнительно ▾" if vis else "Дополнительно ▸")

    def _sync_export_controls(self) -> None:
        ex = self.ctrl.settings.export
        self.bg_toggle.set_value(self.ctrl.settings.background_color)
        self.format_combo.blockSignals(True)
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(ex.format)))
        self.format_combo.blockSignals(False)
        self.quality.blockSignals(True)
        self.quality.setValue(ex.jpeg_quality)
        self.quality.blockSignals(False)
        self.quality.setEnabled(ex.format == "jpg")
        self.quality_lbl.setEnabled(ex.format == "jpg")

    def _background_changed(self, key: str) -> None:
        self.bg_toggle.set_value(key)
        s = self.ctrl.settings.copy()
        s.background_color = key
        self.ctrl.set_settings(s, "Фон: " + BACKGROUND_COLORS[key].lower())

    def _format_changed(self) -> None:
        s = self.ctrl.settings.copy()
        s.export.format = self.format_combo.currentData()
        self.ctrl.set_settings(s, "Формат экспорта")

    def _quality_changed(self, v: int) -> None:
        s = self.ctrl.settings.copy()
        s.export.jpeg_quality = v
        self.ctrl.set_settings(s, "Качество JPEG")

    def choose_output(self) -> None:
        start = self.output_dir() or self.ctrl.app_settings.last_output_folder()
        if start and not Path(start).exists():
            start = str(Path(start).parent)
        folder = QFileDialog.getExistingDirectory(self, "Папка результата", start)
        if not folder:
            return
        if Path(folder).resolve() == Path(self.ctrl.project.source_dir).resolve():
            QMessageBox.warning(self, "Папка результата",
                                "Выберите другую папку: результат не сохраняется рядом с оригиналами.")
            return
        self.ctrl.set_output_dir(folder)

    # ---------------------------------------------------------- экспорт
    def is_busy(self) -> bool:
        return self.worker is not None

    def start_export(self) -> None:
        if self.worker is not None:
            return
        photos = self.ctrl.photos
        incomplete, unconfirmed = self._problems()
        if incomplete:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Не все параметры заданы")
            box.setText(f"У {len(incomplete)} фото не заданы название, освещение, увеличение или номер.")
            box.setInformativeText("Эти фото будут пропущены.")
            go = box.addButton("Заполнить", QMessageBox.ButtonRole.RejectRole)
            box.addButton("Обработать остальные", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(go)
            box.exec()
            if box.clickedButton() is go:
                self.gotoPhoto.emit(incomplete[0], 0)
                return
        if unconfirmed:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Круги не проверены")
            box.setText(f"Не проверено кругов: {len(unconfirmed)}.")
            box.setInformativeText("Использовать круги, найденные автоматически?")
            box.addButton("Обработать", QMessageBox.ButtonRole.AcceptRole)
            go = box.addButton("Проверить", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is go:
                self.gotoPhoto.emit(unconfirmed[0], 1)
                return
        out_dir = self.output_dir()
        if not out_dir:
            self.choose_output()
            out_dir = self.output_dir()
            if not out_dir:
                return
        try:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Папка результата", f"Не удалось создать папку:\n{e}")
            return
        if not self.ctrl.project.output_dir:
            self.ctrl.set_output_dir(out_dir)

        indices = [i for i, p in enumerate(photos) if not p.excluded and not p.missing and p.params_complete()]
        # фото без круга (например, не успели найти) — подставить приблизительный
        for i in indices:
            p = photos[i]
            if p.circle is None and p.width:
                self.ctrl.set_detected_circle(i, project_ops.default_circle(p.width, p.height), 0.0, "default")
        plan = plan_export(photos, indices, out_dir, self.ctrl.settings.export)
        if plan.duplicates:
            r = QMessageBox.question(
                self, "Одинаковые имена",
                f"У {plan.duplicates} фото имя результата совпадает с другим фото или с уже "
                "существующим файлом.\n\nСуществующие файлы не будут перезаписаны: к новым именам "
                "добавится «__повтор_2», «__повтор_3»…\n\nПродолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
        if not plan.items:
            QMessageBox.information(self, "Экспорт", "Нет фотографий для обработки.")
            return
        self.worker = ExportWorker(photos, plan, self.ctrl.settings)
        self.worker.progress.connect(self._on_progress)
        self.worker.itemDone.connect(self._on_item_done)
        self.worker.finishedAll.connect(self._on_finished)
        self.prog.setRange(0, len(plan.items))
        self.prog.setValue(0)
        self.prog_lbl.setText(f"0 / {len(plan.items)}")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Отмена")
        self.side_stack.setCurrentIndex(1)
        self.busyChanged.emit(True)
        log.info("Экспорт: %d фото → %s", len(plan.items), out_dir)
        self.worker.start()

    def cancel_export(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("Останавливаю…")

    def _on_progress(self, done: int, total: int) -> None:
        self.prog.setValue(done)
        self.prog_lbl.setText(f"{done} / {total}")

    def _on_item_done(self, index: int, status: str, msg: str, sig) -> None:
        if status == "done":
            self.ctrl.set_export_result(index, "done", "", msg, sig)
        else:
            self.ctrl.set_export_result(index, "error", msg)

    def _on_finished(self, summary: ExportSummary) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.wait(2000)
            worker.deleteLater()
        self.last_summary = summary
        self.busyChanged.emit(False)
        log.info("Экспорт завершен: %d готово, %d ошибок, отменено=%s", summary.done, len(summary.errors),
                 summary.cancelled)
        if not summary.errors and not summary.cancelled:
            self.ctrl.mark_finished()
        self._show_done(summary)

    def _show_done(self, s: ExportSummary) -> None:
        self.done_title.setText("Остановлено" if s.cancelled else "Готово")
        lines = [f"Обработано: {s.done}"]
        if s.cancelled:
            lines.append("Обработка остановлена. Уже сохраненные файлы остались в папке.")
        self.done_lbl.setText("\n".join(lines))
        self.err_lbl.setText(f"Ошибок: {len(s.errors)}")
        self.err_lbl.setStyleSheet("font-size: 11pt; color: %s;" % ("#b91c1c" if s.errors else "#1f2328"))
        self.err_btn.setVisible(bool(s.errors))
        self.err_btn.setText("Показать")
        self.err_list.clear()
        for idx, name, msg in s.errors:
            self.err_list.addItem(f"{name} — {msg}")
            self.err_list.item(self.err_list.count() - 1).setData(Qt.ItemDataRole.UserRole, idx)
        self.err_list.setVisible(False)
        self.done_path.setText(self.output_dir())
        self.side_stack.setCurrentIndex(2)

    def _toggle_errors(self) -> None:
        vis = not self.err_list.isVisible()
        self.err_list.setVisible(vis)
        self.err_btn.setText("Скрыть" if vis else "Показать")

    def _error_clicked(self, item) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.ctrl.set_current(int(idx))

    def _open_output(self) -> None:
        from .main_window import open_in_explorer

        open_in_explorer(self.output_dir())

    def _back_to_ready(self) -> None:
        self.side_stack.setCurrentIndex(0)
        self.refresh()

    # ---------------------------------------------------------- навигация
    def next_label(self) -> str:
        return "Далее →"

    def accept(self) -> None:
        self.go_next()

    def go_next(self) -> None:
        self.ctrl.set_current(self.ctrl.current_index + 1)

    def go_prev(self) -> None:
        self.ctrl.set_current(self.ctrl.current_index - 1)

    def commit_pending(self) -> None:
        pass

    def shutdown(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(30000)
        self.renderer.cancel()
        self.renderer.wait()
