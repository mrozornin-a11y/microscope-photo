"""Контроллер проекта: единая точка изменения модели, Undo/Redo, автосохранение.

GUI-виджеты не меняют PhotoItem напрямую — только через методы контроллера.
Все пользовательские изменения проходят через QUndoStack.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from ..core import project_ops, state
from ..core.models import Circle, PhotoItem, ProcessingSettings, Project
from ..core.scanner import merge_rescan, scan_folder
from .app_settings import AppSettings

log = logging.getLogger(__name__)

UNDO_LIMIT = 200
MERGE_WINDOW_S = 1.5


class PhotoEditCommand(QUndoCommand):
    """Изменение полей одной или нескольких фотографий (одна запись в истории)."""

    MERGE_ID = 4201

    def __init__(self, ctrl: "ProjectController", text: str,
                 changes: list[tuple[int, dict[str, Any], dict[str, Any]]],
                 merge_key: str | None = None) -> None:
        super().__init__(text)
        self.ctrl = ctrl
        self.changes = changes
        self.merge_key = merge_key
        self.stamp = time.monotonic()

    def redo(self) -> None:
        for idx, _old, new in self.changes:
            self.ctrl._apply_values(idx, new)
        self.ctrl._after_command([c[0] for c in self.changes], self._focus())

    def undo(self) -> None:
        for idx, old, _new in reversed(self.changes):
            self.ctrl._apply_values(idx, old)
        self.ctrl._after_command([c[0] for c in self.changes], self._focus())

    def _focus(self) -> int | None:
        return self.changes[0][0] if len(self.changes) == 1 else None

    def id(self) -> int:  # noqa: A003
        return self.MERGE_ID if self.merge_key else -1

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802
        if not isinstance(other, PhotoEditCommand) or other.merge_key != self.merge_key:
            return False
        if other.stamp - self.stamp > MERGE_WINDOW_S:
            return False
        if [c[0] for c in other.changes] != [c[0] for c in self.changes]:
            return False
        merged = []
        for (idx, old, new), (_i, old2, new2) in zip(self.changes, other.changes):
            o = dict(old)
            for k, v in old2.items():
                o.setdefault(k, v)
            n = dict(new)
            n.update(new2)
            merged.append((idx, o, n))
        self.changes = merged
        self.stamp = other.stamp
        return True


class SettingsCommand(QUndoCommand):
    def __init__(self, ctrl: "ProjectController", text: str,
                 old: ProcessingSettings, new: ProcessingSettings) -> None:
        super().__init__(text)
        self.ctrl = ctrl
        self.old = old.copy()
        self.new = new.copy()

    def redo(self) -> None:
        self.ctrl._apply_settings(self.new)

    def undo(self) -> None:
        self.ctrl._apply_settings(self.old)


class RemovePhotosCommand(QUndoCommand):
    """Убрать фото из партии (файлы на диске не трогаются). Undo возвращает их
    на прежние места со всей разметкой. Несколько фото — одна запись в истории."""

    def __init__(self, ctrl: "ProjectController", indices: list[int]) -> None:
        n = len(indices)
        super().__init__("Убрать фото из проекта" if n == 1 else f"Убрать {n} фото из проекта")
        self.ctrl = ctrl
        self.items = [(i, ctrl.photos[i]) for i in sorted(indices)]
        self.prev_current = ctrl.current_index

    def redo(self) -> None:
        self.ctrl._remove_items([i for i, _ in self.items])

    def undo(self) -> None:
        self.ctrl._insert_items(self.items, self.prev_current)


class ProjectController(QObject):
    projectLoaded = Signal()
    photoListChanged = Signal()     # фото убраны из партии / возвращены (индексы сдвинулись)
    photoChanged = Signal(int)
    currentChanged = Signal(int)
    settingsChanged = Signal()
    stageChanged = Signal(int)
    nameListChanged = Signal()
    outputDirChanged = Signal()

    def __init__(self, app_settings: AppSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app_settings = app_settings
        self.project = Project()
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(UNDO_LIMIT)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(self.save_now)

    # ------------------------------------------------------------ доступ
    @property
    def photos(self) -> list[PhotoItem]:
        return self.project.photos

    @property
    def settings(self) -> ProcessingSettings:
        return self.project.settings

    @property
    def current_index(self) -> int:
        return self.project.current_index

    @property
    def current(self) -> PhotoItem | None:
        if 0 <= self.project.current_index < len(self.project.photos):
            return self.project.photos[self.project.current_index]
        return None

    def has_project(self) -> bool:
        return bool(self.project.photos)

    # ------------------------------------------------------- загрузка
    def open_folder(self, folder: str, saved: Project | None = None, prefill: bool = True) -> None:
        """saved — сохраненная разметка папки; prefill — подставить в первое фото
        последние освещение/увеличение (только для папки, открытой впервые)."""
        if saved is not None:
            project = saved
            project.photos = merge_rescan(saved.photos, folder, saved.removed_paths,
                                          saved.saved_at or None, saved.removed_fp)
            project.source_dir = folder
            project.current_index = min(project.current_index, max(0, len(project.photos) - 1))
        else:
            project = Project(source_dir=folder, settings=self.app_settings.processing())
            project.photos = scan_folder(folder)
            if project.photos and prefill:
                first = project.photos[0]
                first.light_mode = self.app_settings.last_light()
                first.magnification = self.app_settings.last_mag()
                first.photo_number = 1
            project.output_dir = ""
        self.project = project
        self.undo_stack.clear()
        self.app_settings.set_last_folder(folder)
        self.projectLoaded.emit()
        self.schedule_save()

    def start_new_project(self) -> None:
        """«Начать новый проект»: удалить сохраненную разметку этой папки и открыть ее
        как совершенно новую партию. Исходные файлы не трогаются; глобальные
        настройки (резкость, шкала, окно) сохраняются."""
        folder = self.project.source_dir
        self._save_timer.stop()
        state.start_new(folder)
        self.project = Project()
        self.open_folder(folder, None, prefill=False)

    def close_project(self) -> None:
        self.save_now()
        self.project = Project()
        self.undo_stack.clear()
        self.projectLoaded.emit()

    # ------------------------------------------------------ навигация
    def set_current(self, index: int) -> None:
        if not self.photos:
            return
        index = max(0, min(index, len(self.photos) - 1))
        if index != self.project.current_index:
            self.project.current_index = index
            self.currentChanged.emit(index)
            self.schedule_save(dirty=False)

    def set_stage(self, stage: int) -> None:
        if stage != self.project.stage:
            self.project.stage = stage
            self.stageChanged.emit(stage)
            self.schedule_save(dirty=False)

    # ------------------------------------------------- редактирование
    def _old_values(self, p: PhotoItem, new: dict[str, Any]) -> dict[str, Any]:
        return {k: getattr(p, k) for k in new}

    def edit(self, index: int, values: dict[str, Any], text: str, merge_key: str | None = None) -> None:
        self.edit_many([(index, values)], text, merge_key)

    def edit_many(self, changes: list[tuple[int, dict[str, Any]]], text: str,
                  merge_key: str | None = None) -> bool:
        triples = []
        for idx, new in changes:
            p = self.photos[idx]
            new = {k: v for k, v in new.items() if getattr(p, k) != v}
            if not new:
                continue
            if p.export_status:
                new["export_status"] = ""
            triples.append((idx, self._old_values(p, new), new))
        if not triples:
            return False
        self.undo_stack.push(PhotoEditCommand(self, text, triples, merge_key))
        return True

    def edit_with_old(self, index: int, old: dict[str, Any], new: dict[str, Any], text: str) -> None:
        """Для перетаскивания: значение уже применено «вживую», в историю пишем исходное."""
        if old == new:
            return
        p = self.photos[index]
        if p.export_status:
            old = dict(old, export_status=p.export_status)
            new = dict(new, export_status="")
        self.undo_stack.push(PhotoEditCommand(self, text, [(index, old, new)]))

    def live_values(self, index: int, values: dict[str, Any]) -> None:
        """Временное изменение без записи в историю (во время перетаскивания)."""
        p = self.photos[index]
        for k, v in values.items():
            setattr(p, k, v)
        self.photoChanged.emit(index)

    def _apply_values(self, index: int, values: dict[str, Any]) -> None:
        p = self.photos[index]
        for k, v in values.items():
            setattr(p, k, v)
        if "light_mode" in values or "magnification" in values:
            self.app_settings.remember_params(p.light_mode, p.magnification)
        self.photoChanged.emit(index)

    def _after_command(self, indices: list[int], focus: int | None) -> None:
        self.project.finished = False
        if focus is not None and focus != self.project.current_index:
            self.set_current(focus)
        self.schedule_save()

    # --------------------------------------------- состав партии
    def remove_photos(self, indices: list[int]) -> int:
        """Убрать фото из партии (через Undo). Возвращает число убранных."""
        n = len(self.photos)
        indices = sorted({i for i in indices if 0 <= i < n})
        if not indices or len(indices) >= n:
            return 0
        self.undo_stack.push(RemovePhotosCommand(self, indices))
        return len(indices)

    def _remove_items(self, indices: list[int]) -> None:
        cur = self.project.current_index
        removed_set = set(indices)
        for i in reversed(indices):
            p = self.photos.pop(i)
            if p.source_path not in self.project.removed_paths:
                self.project.removed_paths.append(p.source_path)
            if p.has_fingerprint():
                self.project.removed_fp[p.source_path] = [p.file_size, p.file_mtime_ns]
        if cur in removed_set:
            # ближайшая оставшаяся: следующая за первой убранной, иначе последняя
            new_cur = indices[0]
        else:
            new_cur = cur - sum(1 for i in indices if i < cur)
        self.project.current_index = max(0, min(new_cur, len(self.photos) - 1))
        self._after_list_change()

    def _insert_items(self, items: list[tuple[int, PhotoItem]], current: int) -> None:
        for i, p in items:
            self.photos.insert(i, p)
            if p.source_path in self.project.removed_paths:
                self.project.removed_paths.remove(p.source_path)
            self.project.removed_fp.pop(p.source_path, None)
        self.project.current_index = max(0, min(current, len(self.photos) - 1))
        self._after_list_change()

    def _after_list_change(self) -> None:
        self.project.finished = False
        self.photoListChanged.emit()
        self.currentChanged.emit(self.project.current_index)
        self.schedule_save()

    def inherit_into(self, index: int) -> None:
        new = project_ops.inherit_values(self.photos, index)
        if new:
            self.edit(index, new, "Параметры предыдущего фото")

    def set_detected_circle(self, index: int, circle: Circle, confidence: float, source: str = "auto") -> bool:
        """Результат автоопределения. Не трогает круги, которые проверил или правил пользователь."""
        if not (0 <= index < len(self.photos)):
            return False
        p = self.photos[index]
        if p.circle_confirmed or p.circle_source not in ("", "auto", "default"):
            return False
        p.circle = circle
        p.circle_source = source
        p.detect_confidence = confidence
        self.photoChanged.emit(index)
        self.schedule_save(dirty=False)
        return True

    def set_photo_size(self, index: int, w: int, h: int) -> None:
        p = self.photos[index]
        if (p.width, p.height) != (w, h):
            p.width, p.height = w, h
            self.schedule_save(dirty=False)

    def set_export_result(self, index: int, status: str, error: str = "",
                          output_path: str = "", signature: list[float] | None = None) -> None:
        p = self.photos[index]
        p.export_status = status
        p.export_error = error
        if output_path:
            p.output_path = output_path
            p.output_signature = list(signature or [])
        self.photoChanged.emit(index)
        self.schedule_save(dirty=False)

    # ------------------------------------------------------ настройки
    def set_settings(self, new: ProcessingSettings, text: str = "Изменение настроек") -> None:
        if new.to_dict() == self.settings.to_dict():
            return
        self.undo_stack.push(SettingsCommand(self, text, self.settings, new))

    def _apply_settings(self, s: ProcessingSettings) -> None:
        self.project.settings = s.copy()
        self.app_settings.set_processing(self.project.settings)
        self.project.finished = False
        self.settingsChanged.emit()
        self.schedule_save()

    def set_output_dir(self, path: str) -> None:
        self.project.output_dir = path
        self.app_settings.set_last_output_folder(path)
        self.outputDirChanged.emit()
        self.schedule_save(dirty=False)

    def set_name_list(self, names: list[str]) -> None:
        self.project.name_list = names
        self.nameListChanged.emit()
        self.schedule_save(dirty=False)

    def mark_finished(self) -> None:
        self.project.finished = True
        self.schedule_save(dirty=False)

    # -------------------------------------------------- сохранение
    def schedule_save(self, dirty: bool = True) -> None:
        if dirty:
            self.project.finished = False
        if self.project.source_dir:
            self._save_timer.start()

    def save_now(self) -> None:
        self._save_timer.stop()
        if not self.project.source_dir or not self.project.photos:
            return
        try:
            state.save_project(self.project)
        except Exception:
            log.exception("Не удалось сохранить состояние")
