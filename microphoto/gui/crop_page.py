"""Этап 2. Поле зрения: проверка и правка найденного круга."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QMessageBox, QPushButton, QVBoxLayout, QHBoxLayout, QWidget

from ..core import naming, project_ops
from ..core.models import Circle
from .controller import ProjectController
from .dialogs import ApplyCircleDialog
from .media import MediaService
from .photo_page import section
from .widgets.crop_viewer import CropViewer

LOW_CONFIDENCE = 0.5


class CropPage(QWidget):
    finished = Signal()

    def __init__(self, ctrl: ProjectController, media: MediaService, parent=None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.media = media
        self._find_tokens: dict[int, int] = {}      # «Найти заново» — по индексу фото
        self._prior_tokens: dict[int, int] = {}     # уточнение с учетом предыдущего круга

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.viewer = CropViewer()
        self.viewer.circleLive.connect(self._on_live)
        self.viewer.circleDragFinished.connect(self._on_drag_finished)
        self.viewer.circleWheel.connect(self._on_wheel)
        root.addWidget(self.viewer, 1)

        side = QFrame()
        side.setObjectName("SidePanel")
        side.setFixedWidth(300)
        root.addWidget(side)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)

        lay.addWidget(section("Поле зрения"))
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 11pt;")
        lay.addWidget(self.status)
        self.name_lbl = QLabel()
        self.name_lbl.setObjectName("Muted")
        self.name_lbl.setWordWrap(True)
        lay.addWidget(self.name_lbl)
        lay.addSpacing(8)

        self.find_btn = QPushButton("Найти заново")
        self.find_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.find_btn.clicked.connect(self.find_again)
        lay.addWidget(self.find_btn)
        self.prev_btn = QPushButton("Как на предыдущем фото")
        self.prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prev_btn.clicked.connect(self.like_previous)
        lay.addWidget(self.prev_btn)
        self.apply_btn = QPushButton("Применить этот круг дальше…")
        self.apply_btn.setObjectName("Link")
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_btn.clicked.connect(self.apply_forward)
        lay.addWidget(self.apply_btn, 0, Qt.AlignmentFlag.AlignLeft)

        lay.addStretch(1)
        self.progress_lbl = QLabel()
        self.progress_lbl.setObjectName("Muted")
        lay.addWidget(self.progress_lbl)
        hint = QLabel("Перетащите круг мышью\n"
                      "Край круга или колесо — радиус\n"
                      "Shift + колесо — точнее\n"
                      "Ctrl + колесо — масштаб\n"
                      "Двойной щелчок — вписать в окно\n"
                      "Enter — круг верный, далее")
        hint.setObjectName("Hint")
        lay.addWidget(hint)

        ctrl.currentChanged.connect(self._on_current)
        ctrl.photoChanged.connect(self._on_photo_changed)
        ctrl.projectLoaded.connect(self._on_project)
        ctrl.photoListChanged.connect(self._on_project)    # индексы сдвинулись — ожидания сбросить
        media.previewReady.connect(self._on_preview_ready)
        media.detectionDone.connect(self._on_detection)

    # -------------------------------------------------------------- показ
    def _on_project(self) -> None:
        self._find_tokens.clear()
        self._prior_tokens.clear()

    def on_enter(self) -> None:
        self.refresh()
        self.viewer.setFocus()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.refresh()

    def _on_current(self, _i: int) -> None:
        if self.isVisible():
            self.refresh()

    def _on_photo_changed(self, i: int) -> None:
        if self.isVisible():
            if i == self.ctrl.current_index:
                self.refresh(load_image=False)
            else:
                self._update_progress()

    def _on_preview_ready(self, i: int) -> None:
        if i == self.ctrl.current_index and self.isVisible():
            self.refresh()

    def _display_circle(self) -> Circle | None:
        p = self.ctrl.current
        if p is None:
            return None
        if p.circle is not None:
            return p.circle
        if p.width:
            return project_ops.default_circle(p.width, p.height)
        return None

    def refresh(self, load_image: bool = True) -> None:
        p = self.ctrl.current
        if p is None:
            return
        i = self.ctrl.current_index
        if load_image:
            if p.missing:
                self.viewer.show_message("Файл не найден")
            elif self.media.error(i):
                self.viewer.show_message("Не удалось открыть файл")
            else:
                self.viewer.set_image(self.media.preview(i), (p.width, p.height) if p.width else None,
                                      keep_view=True)
        self.viewer.set_circle(self._display_circle() if self.viewer.has_image() else None)
        self.viewer.editable = not p.excluded
        prev_i = project_ops.previous_active(self.ctrl.photos, i)
        self.prev_btn.setEnabled(not p.excluded and prev_i is not None
                                 and self.ctrl.photos[prev_i].circle is not None)
        self.find_btn.setEnabled(not p.excluded and not p.missing)
        self.apply_btn.setEnabled(not p.excluded and p.circle is not None)

        if p.excluded:
            text, color = "Это фото не будет обработано", "#6b7280"
        elif p.missing or self.media.error(i):
            text, color = "Файл не удалось открыть — он будет пропущен", "#b91c1c"
        elif p.circle_confirmed:
            text, color = "✓ Круг проверен", "#15803d"
        elif p.circle is None:
            text, color = "Определяю поле зрения…", "#6b7280"
        elif i in self._find_tokens or i in self._prior_tokens:
            text, color = "Уточняю круг…", "#6b7280"
        elif p.circle_source == "default" or (p.detect_confidence is not None and p.detect_confidence < LOW_CONFIDENCE):
            text, color = "Круг найден неуверенно — проверьте и при необходимости поправьте", "#b45309"
        else:
            text, color = "Круг найден автоматически.\nЕсли он верный — нажмите Enter.", "#1f2328"
        self.status.setText(text)
        self.status.setStyleSheet(f"font-size: 11pt; color: {color};")
        out = naming.output_display(p, self.ctrl.settings.export.format)
        self.name_lbl.setText(out or "Параметры фото не заполнены")
        self._update_progress()

    def _update_progress(self) -> None:
        active = [p for p in self.ctrl.photos if not p.excluded and not p.missing]
        done = sum(1 for p in active if p.circle_confirmed)
        self.progress_lbl.setText(f"Проверено кругов: {done} из {len(active)}")

    # -------------------------------------------------------- правка мышью
    def _circle_values(self, c: Circle) -> dict:
        return {"circle": c, "circle_source": "manual", "circle_confirmed": True}

    def _on_live(self, c: Circle) -> None:
        self.ctrl.live_values(self.ctrl.current_index, {"circle": c})

    def _on_drag_finished(self, old: Circle, new: Circle, mode: str) -> None:
        i = self.ctrl.current_index
        p = self.ctrl.current
        old_vals = {"circle": old, "circle_source": p.circle_source, "circle_confirmed": p.circle_confirmed}
        # во время перетаскивания circle уже изменен «вживую» — в историю пишем исходное значение
        self._cancel_pending(i)
        self.ctrl.edit_with_old(i, old_vals, self._circle_values(new),
                                "Перемещение круга" if mode == "move" else "Изменение радиуса")

    def _on_wheel(self, c: Circle) -> None:
        i = self.ctrl.current_index
        self._cancel_pending(i)
        self.ctrl.edit(i, self._circle_values(c), "Изменение радиуса", merge_key=f"radius:{i}")

    def _cancel_pending(self, i: int) -> None:
        self._find_tokens.pop(i, None)
        self._prior_tokens.pop(i, None)

    # -------------------------------------------------------------- кнопки
    def find_again(self) -> None:
        i = self.ctrl.current_index
        self._prior_tokens.pop(i, None)
        self._find_tokens[i] = self.media.redetect(i, None)
        self.refresh(load_image=False)

    def _request_prior(self, i: int) -> None:
        """Перешли к непроверенному фото после проверенного — уточнить круг с подсказкой."""
        p = self.ctrl.photos[i]
        if p.circle_confirmed or p.circle_source not in ("", "auto", "default") or p.excluded or p.missing:
            return
        prev_i = project_ops.previous_active(self.ctrl.photos, i)
        if prev_i is None:
            return
        prev = self.ctrl.photos[prev_i]
        if not prev.circle_confirmed or prev.circle is None:
            return
        prior = project_ops.circle_for_size(prev.circle, prev, p)
        self._prior_tokens[i] = self.media.redetect(i, prior)

    def _on_detection(self, i: int, circle: Circle, confidence: float, token: int) -> None:
        if self._find_tokens.get(i) == token:
            del self._find_tokens[i]
            self.ctrl.edit(i, {"circle": circle, "circle_source": "auto", "circle_confirmed": False,
                               "detect_confidence": confidence}, "Найти круг заново")
            if confidence < LOW_CONFIDENCE:
                self.window().statusBar().showMessage(
                    "Поле зрения не найдено уверенно — поправьте круг вручную", 5000)
        elif self._prior_tokens.get(i) == token:
            del self._prior_tokens[i]
            self.ctrl.set_detected_circle(i, circle, confidence)
        if i == self.ctrl.current_index and self.isVisible():
            self.refresh(load_image=False)

    def like_previous(self) -> None:
        i = self.ctrl.current_index
        prev_i = project_ops.previous_active(self.ctrl.photos, i)
        if prev_i is None or self.ctrl.photos[prev_i].circle is None:
            return
        prev = self.ctrl.photos[prev_i]
        self._cancel_pending(i)
        c = project_ops.circle_for_size(prev.circle, prev, self.ctrl.photos[i])
        self.ctrl.edit(i, {"circle": c, "circle_source": "previous", "circle_confirmed": True},
                       "Круг как на предыдущем фото")

    def apply_forward(self) -> None:
        i = self.ctrl.current_index
        p = self.ctrl.current
        if p is None or p.circle is None:
            return
        remaining = len(project_ops.following_active(self.ctrl.photos, i, None))
        if remaining == 0:
            QMessageBox.information(self, "Применить дальше", "Это последняя фотография.")
            return
        dlg = ApplyCircleDialog(remaining, self)
        if not dlg.exec():
            return
        changes = [(i, {"circle_confirmed": True})] if not p.circle_confirmed else []
        changes += project_ops.apply_circle_forward(self.ctrl.photos, i, dlg.count())
        for j, _ in changes:
            self._cancel_pending(j)
        if self.ctrl.edit_many(changes, "Применить круг дальше"):
            self.window().statusBar().showMessage(f"Круг применен к {len(changes)} фото", 4000)

    # ----------------------------------------------------------- навигация
    def confirm_current(self) -> None:
        i = self.ctrl.current_index
        p = self.ctrl.current
        if p is None or p.excluded or p.missing or p.circle_confirmed:
            return
        c = p.circle or self._display_circle()
        if c is None:
            return
        self._cancel_pending(i)
        self.ctrl.edit(i, {"circle": c, "circle_confirmed": True,
                           "circle_source": p.circle_source or "default"}, "Круг подтвержден")

    def next_label(self) -> str:
        if self.ctrl.current_index >= len(self.ctrl.photos) - 1:
            return "Круг верный → Готово"
        return "Круг верный, далее →"

    def accept(self) -> None:
        """Enter: круг верный → следующее фото."""
        self.confirm_current()
        i = self.ctrl.current_index
        if i >= len(self.ctrl.photos) - 1:
            self.finished.emit()
            return
        self.ctrl.set_current(i + 1)
        self._request_prior(i + 1)
        self.refresh(load_image=False)

    def go_next(self) -> None:
        i = self.ctrl.current_index
        if i < len(self.ctrl.photos) - 1:
            self.ctrl.set_current(i + 1)
            self._request_prior(i + 1)

    def go_prev(self) -> None:
        self.ctrl.set_current(self.ctrl.current_index - 1)

    def commit_pending(self) -> None:
        pass
