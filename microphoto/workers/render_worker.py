"""Фоновая отрисовка итогового preview (из оригинала, в полном разрешении)."""

from __future__ import annotations

import copy
import logging

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from ..core.models import PhotoItem, ProcessingSettings
from ..core.pipeline import render

log = logging.getLogger(__name__)


def pil_to_qimage(img: Image.Image) -> QImage:
    if img.mode != "RGB":
        img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    return qimg.copy()      # копия владеет памятью


class _Signals(QObject):
    done = Signal(int, object, str)       # token, QImage | None, ошибка


class _Job(QRunnable):
    def __init__(self, token: int, photo: PhotoItem, settings: ProcessingSettings, signals: _Signals,
                 max_side: int | None) -> None:
        super().__init__()
        self.token = token
        self.photo = photo
        self.settings = settings
        self.signals = signals
        self.max_side = max_side

    def run(self) -> None:
        try:
            r = render(self.photo, self.settings, max_side=self.max_side)
            self.signals.done.emit(self.token, pil_to_qimage(r.image), "")
        except Exception as e:
            log.warning("Preview не построен: %s", e)
            self.signals.done.emit(self.token, None, str(e))


class FinalRenderer(QObject):
    """Отрисовывает только последний запрос; устаревшие результаты отбрасываются."""

    ready = Signal(object)        # QImage
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._token = 0

    def request(self, photo: PhotoItem, settings: ProcessingSettings, max_side: int | None = None) -> None:
        self._token += 1
        self._pool.clear()       # незапущенные задачи больше не нужны
        self._pool.start(_Job(self._token, copy.deepcopy(photo), settings.copy(), self._signals, max_side))

    def cancel(self) -> None:
        self._token += 1
        self._pool.clear()

    def _on_done(self, token: int, img, err: str) -> None:
        if token != self._token:
            return
        if img is None:
            self.failed.emit(err)
        else:
            self.ready.emit(img)

    def wait(self) -> None:
        self._pool.waitForDone(10000)
