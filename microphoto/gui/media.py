"""Сервис изображений для GUI: миниатюры и preview с фоновой подготовкой."""

from __future__ import annotations

import logging
from collections import OrderedDict

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap

from ..core.models import Circle
from ..workers.media_worker import PRIO_BACKGROUND, PRIO_CURRENT, PRIO_NEAR, MediaWorker, Prepared
from .controller import ProjectController

log = logging.getLogger(__name__)

PIXMAP_CACHE = 6


class MediaService(QObject):
    thumbReady = Signal(int)
    previewReady = Signal(int)
    failed = Signal(int, str)
    detectionDone = Signal(int, object, float, int)   # индекс, Circle, уверенность, token

    def __init__(self, ctrl: ProjectController, parent=None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self._thumbs: dict[str, QImage] = {}
        self._previews: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self._pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self._index: dict[str, int] = {}
        self._detect_token = 0
        self._detect_tokens: dict[str, int] = {}
        # Два потока: миниатюры/preview и автоопределение кругов не ждут друг друга
        self.worker = MediaWorker()
        self.worker.prepared.connect(self._on_prepared)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()
        self.det_worker = MediaWorker(emit_prepared=False)
        self.det_worker.detected.connect(self._on_detected)
        self.det_worker.failed.connect(self._on_failed)
        self.det_worker.start()
        ctrl.projectLoaded.connect(self._on_project)
        ctrl.photoListChanged.connect(self._reindex)
        ctrl.currentChanged.connect(self._on_current)

    def shutdown(self) -> None:
        self.worker.stop()
        self.det_worker.stop()

    # -------------------------------------------------------------------
    def _on_project(self) -> None:
        self.worker.reset()
        self.det_worker.reset()
        self._index = {p.source_path: i for i, p in enumerate(self.ctrl.photos)}
        self._pixmaps.clear()
        self._detect_tokens.clear()
        self._on_current(self.ctrl.current_index)
        for p in self.ctrl.photos:
            if not p.missing:
                self.worker.request(p.source_path, PRIO_BACKGROUND)
                if p.circle is None:
                    self.det_worker.request(p.source_path, PRIO_BACKGROUND, detect=True)

    def _reindex(self) -> None:
        """Состав партии изменился — результаты фоновых задач ищем по пути, а не по старому индексу."""
        self._index = {p.source_path: i for i, p in enumerate(self.ctrl.photos)}

    def _on_current(self, index: int) -> None:
        photos = self.ctrl.photos
        for j, prio in ((index, PRIO_CURRENT), (index + 1, PRIO_NEAR), (index - 1, PRIO_NEAR), (index + 2, PRIO_NEAR)):
            if not (0 <= j < len(photos)) or photos[j].missing:
                continue
            if photos[j].source_path not in self._previews:
                self.worker.request(photos[j].source_path, prio)
            if photos[j].circle is None:
                self.det_worker.request(photos[j].source_path, prio, detect=True)

    def _on_prepared(self, res: Prepared) -> None:
        self._thumbs[res.path] = res.thumb
        self._previews[res.path] = res.preview_path
        i = self._index.get(res.path)
        if i is None:
            return
        self.ctrl.set_photo_size(i, *res.full_size)
        self.thumbReady.emit(i)
        self.previewReady.emit(i)

    def _on_detected(self, path: str, circle: Circle, confidence: float, token: int) -> None:
        i = self._index.get(path)
        if i is None:
            return
        expected = self._detect_tokens.get(path, 0)
        if token != expected:
            return     # устаревший результат
        if token == 0:
            self.ctrl.set_detected_circle(i, circle, confidence)
        else:
            self.detectionDone.emit(i, circle, confidence, token)

    def _on_failed(self, path: str, msg: str) -> None:
        self._errors[path] = msg
        i = self._index.get(path)
        if i is not None:
            self.failed.emit(i, msg)
            self.thumbReady.emit(i)

    # -------------------------------------------------------------------
    def thumbnail(self, index: int) -> QImage | None:
        p = self.ctrl.photos[index]
        return self._thumbs.get(p.source_path)

    def error(self, index: int) -> str | None:
        return self._errors.get(self.ctrl.photos[index].source_path)

    def preview(self, index: int) -> QPixmap | None:
        if not (0 <= index < len(self.ctrl.photos)):
            return None
        path = self.ctrl.photos[index].source_path
        pm = self._pixmaps.get(path)
        if pm is not None:
            self._pixmaps.move_to_end(path)
            return pm
        prev = self._previews.get(path)
        if prev is None:
            self.worker.request(path, PRIO_CURRENT)
            return None
        pm = QPixmap(prev)
        if pm.isNull():
            return None
        self._pixmaps[path] = pm
        while len(self._pixmaps) > PIXMAP_CACHE:
            self._pixmaps.popitem(last=False)
        return pm

    def preview_path(self, index: int) -> str | None:
        return self._previews.get(self.ctrl.photos[index].source_path)

    def redetect(self, index: int, prior: Circle | None, priority: int = PRIO_CURRENT) -> int:
        """Запросить автоопределение заново. Возвращает token запроса."""
        path = self.ctrl.photos[index].source_path
        self._detect_token += 1
        self._detect_tokens[path] = self._detect_token
        self.det_worker.request_detect(path, prior, self._detect_token, priority)
        return self._detect_token

    def detect_tokens_for(self, index: int) -> int:
        return self._detect_tokens.get(self.ctrl.photos[index].source_path, 0)

