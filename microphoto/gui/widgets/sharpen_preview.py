"""Просмотр резкости: До / После, масштаб 100 % (пиксель в пиксель), удержание — оригинал.

Показывается обрезанное поле зрения в ПОЛНОМ разрешении оригинала.
«После» считается только для видимой части кадра (с небольшим запасом по
краям) — так ползунок отзывается быстро, а результат совпадает с экспортом:
резкость берет радиус от диаметра всего поля зрения, а не фрагмента.
"""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem

from ...core.cropper import apply_mask
from ...core.models import SharpenSettings
from ...core.sharpness import sharpen
from ...workers.render_worker import pil_to_qimage
from .image_viewer import ImageViewer

PAD = 12            # запас по краям фрагмента: резкость использует соседние пиксели


class SharpenPreview(ImageViewer):
    busyChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.wheel_zoom = True
        self.left_drag_pan = True
        self._src: Image.Image | None = None      # обрезка без фона (реальные пиксели)
        self._mask: Image.Image | None = None
        self._background = "black"
        self._settings = SharpenSettings()
        self._show_after = True
        self._holding_original = False
        self._after = QGraphicsPixmapItem()
        self._after.setZValue(1)
        self._after.setTransformationMode(self._pix.transformationMode())
        self.scene().addItem(self._after)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._update_after)
        self.zoomChanged.connect(self.schedule)
        self.horizontalScrollBar().valueChanged.connect(self.schedule)
        self.verticalScrollBar().valueChanged.connect(self.schedule)

    # ---------------------------------------------------------------- данные
    def set_source(self, src: Image.Image, mask: Image.Image) -> None:
        self._src = src
        self._mask = mask
        self._rebuild_before()

    def set_background(self, background: str) -> None:
        if background != self._background:
            self._background = background
            self._rebuild_before()

    def set_settings(self, s: SharpenSettings) -> None:
        self._settings = SharpenSettings(s.enabled, s.amount, s.method)
        self.schedule()

    def set_show_after(self, on: bool) -> None:
        self._show_after = on
        self._apply_visibility()

    def hold_original(self, on: bool) -> None:
        """Пока удерживается — показать оригинал."""
        self._holding_original = on
        self._apply_visibility()

    def zoom_100(self, on: bool) -> None:
        if not self.has_image():
            return
        if on:
            center = self.mapToScene(self.viewport().rect().center())
            if self._fit:
                w, h = self.full_size()
                center = QPointF(w / 2, h / 2)
            self.zoom_to(1.0 / self.devicePixelRatioF(), center)
        else:
            self.fit()
        self.schedule()

    # ---------------------------------------------------------------- отрисовка
    def _rebuild_before(self) -> None:
        if self._src is None or self._mask is None:
            return
        before = apply_mask(self._src, self._mask, self._background)
        self.set_image(QPixmap.fromImage(pil_to_qimage(before)), before.size, keep_view=True)
        self.schedule()

    def _apply_visibility(self) -> None:
        visible = (self._show_after and not self._holding_original and self._settings.enabled
                   and self._settings.amount > 0)
        self._after.setVisible(visible)

    def schedule(self, *_args) -> None:
        self._timer.start()

    def _update_after(self) -> None:
        self._apply_visibility()
        if self._src is None or not (self._settings.enabled and self._settings.amount > 0):
            return
        W, H = self._src.size
        vis = self.mapToScene(self.viewport().rect()).boundingRect().intersected(QRectF(0, 0, W, H))
        if vis.isEmpty():
            return
        x1, y1 = max(0, int(vis.left()) - 1), max(0, int(vis.top()) - 1)
        x2, y2 = min(W, int(vis.right()) + 2), min(H, int(vis.bottom()) + 2)
        px1, py1 = max(0, x1 - PAD), max(0, y1 - PAD)
        px2, py2 = min(W, x2 + PAD), min(H, y2 + PAD)
        region = self._src.crop((px1, py1, px2, py2))
        sharp = sharpen(region, self._settings, diameter=W)
        inner = (x1 - px1, y1 - py1, x1 - px1 + (x2 - x1), y1 - py1 + (y2 - y1))
        sharp = sharp.crop(inner)
        sharp = apply_mask(sharp, self._mask.crop((x1, y1, x2, y2)), self._background)
        self._after.setPixmap(QPixmap.fromImage(pil_to_qimage(sharp)))
        self._after.setPos(x1, y1)
        self._apply_visibility()
