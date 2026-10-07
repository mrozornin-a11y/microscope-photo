"""Фоновая подготовка: миниатюры, уменьшенные копии, автоопределение круга.

Один поток с очередью приоритетов: текущая фотография обрабатывается
первой, затем соседние, затем все остальные по порядку.
"""

from __future__ import annotations

import itertools
import logging
import queue
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ..core import cache
from ..core.circle_detector import detect_circle
from ..core.models import Circle

log = logging.getLogger(__name__)

PRIO_CURRENT = 0
PRIO_NEAR = 1
PRIO_BACKGROUND = 5


@dataclass(order=True)
class _Task:
    priority: int
    seq: int
    kind: str = field(compare=False)            # prepare / detect / stop
    path: str = field(compare=False, default="")
    detect: bool = field(compare=False, default=False)
    prior: Circle | None = field(compare=False, default=None)
    token: int = field(compare=False, default=0)


@dataclass
class Prepared:
    path: str
    thumb: QImage
    preview_path: str
    full_size: tuple[int, int]


class MediaWorker(QThread):
    prepared = Signal(object)                   # Prepared
    detected = Signal(str, object, float, int)  # path, Circle (полные координаты), уверенность, token
    failed = Signal(str, str)                   # path, сообщение

    def __init__(self, emit_prepared: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._emit_prepared = emit_prepared
        self._q: queue.PriorityQueue[_Task] = queue.PriorityQueue()
        self._seq = itertools.count()
        self._done: dict[str, cache.CachedMedia] = {}
        self._detected: set[str] = set()
        self._failed: set[str] = set()

    # --- API (из GUI-потока) -------------------------------------------
    def request(self, path: str, priority: int, detect: bool = False) -> None:
        self._q.put(_Task(priority, next(self._seq), "prepare", path, detect))

    def request_detect(self, path: str, prior: Circle | None, token: int, priority: int = PRIO_CURRENT) -> None:
        self._q.put(_Task(priority, next(self._seq), "detect", path, True, prior, token))

    def reset(self) -> None:
        """Сбросить очередь (новая партия фотографий)."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self._detected.clear()

    def stop(self) -> None:
        self.reset()
        self._q.put(_Task(-1, next(self._seq), "stop"))
        self.wait(5000)

    # --- поток ---------------------------------------------------------
    def run(self) -> None:
        while True:
            task = self._q.get()
            if task.kind == "stop":
                return
            try:
                self._handle(task)
            except Exception as e:  # ошибки одного файла не должны останавливать поток
                log.exception("Ошибка подготовки %s", task.path)
                if task.path not in self._failed:
                    self._failed.add(task.path)
                    self.failed.emit(task.path, str(e))

    def _handle(self, task: _Task) -> None:
        path = task.path
        if path in self._failed:
            return
        media = self._done.get(path)
        if media is None:
            media = cache.get_or_create(path)
            self._done[path] = media
            if self._emit_prepared:
                thumb = QImage(str(media.thumb_path))
                self.prepared.emit(Prepared(path, thumb, str(media.preview_path), media.full_size))
        if task.kind == "detect" or (task.detect and path not in self._detected):
            self._detected.add(path)
            with Image.open(media.preview_path) as im:
                arr = np.asarray(im.convert("RGB"))
            k = arr.shape[1] / media.full_size[0]
            prior = task.prior.scaled(k) if task.prior is not None else None
            det = detect_circle(arr, prior)
            self.detected.emit(path, det.circle.scaled(1 / k), det.confidence, task.token)
