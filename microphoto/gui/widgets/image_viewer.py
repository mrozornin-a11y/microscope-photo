"""Просмотр изображения: вписывание в окно, масштаб колесом, перетаскивание.

Координаты сцены = пиксели исходного (повернутого) изображения, даже если
показывается уменьшенная копия. Поэтому круг поля зрения рисуется прямо
в координатах оригинала.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView

from .. import theme

MAX_ZOOM = 6.0      # экранных пикселей на пиксель оригинала


class ImageViewer(QGraphicsView):
    zoomChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor(theme.VIEWER_BG))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix = QGraphicsPixmapItem()
        self._pix.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._pix.setZValue(0)
        self._scene.addItem(self._pix)
        self._msg = QGraphicsSimpleTextItem()
        self._msg.setBrush(QColor("#9aa0a8"))
        self._msg.setZValue(10)
        self._scene.addItem(self._msg)
        self._fit = True
        self._full = (0, 0)
        self._panning = False
        self._pan_start = QPointF()
        self.wheel_zoom = True          # обычное колесо = масштаб
        self.left_drag_pan = True

    # ------------------------------------------------------------------
    def has_image(self) -> bool:
        return not self._pix.pixmap().isNull()

    def full_size(self) -> tuple[int, int]:
        return self._full

    def set_image(self, pixmap: QPixmap | None, full_size: tuple[int, int] | None = None,
                  keep_view: bool = False) -> None:
        if pixmap is None or pixmap.isNull():
            self.show_message("Загрузка…")
            return
        self._msg.setVisible(False)
        fw, fh = full_size or (pixmap.width(), pixmap.height())
        if not fw or not fh:
            fw, fh = pixmap.width(), pixmap.height()
        same_geometry = keep_view and self._full == (fw, fh)
        self._full = (fw, fh)
        self._pix.setPixmap(pixmap)
        self._pix.setScale(fw / pixmap.width())
        self._pix.setVisible(True)
        margin = max(fw, fh) * 0.25
        self._scene.setSceneRect(QRectF(-margin, -margin, fw + 2 * margin, fh + 2 * margin))
        if not same_geometry:
            self._fit = True
        if self._fit:
            self.fit()

    def show_message(self, text: str) -> None:
        self._pix.setPixmap(QPixmap())
        self._pix.setVisible(False)
        self._msg.setText(text)
        self._msg.setVisible(True)
        self.resetTransform()
        br = self._msg.boundingRect()
        self._scene.setSceneRect(QRectF(-200, -100, 400, 200))
        self._msg.setPos(-br.width() / 2, -br.height() / 2)
        self.centerOn(0, 0)

    def image_rect(self) -> QRectF:
        return QRectF(0, 0, *self._full)

    def fit(self) -> None:
        self._fit = True
        if not self.has_image():
            return
        rect = self.image_rect()
        vp = self.viewport().rect()
        if rect.isEmpty() or vp.isEmpty():
            return
        pad = 16
        k = min((vp.width() - 2 * pad) / rect.width(), (vp.height() - 2 * pad) / rect.height())
        if k <= 0:
            return
        self.resetTransform()
        self.scale(k, k)
        self.centerOn(rect.center())
        self.zoomChanged.emit()

    def fit_scale(self) -> float:
        rect = self.image_rect()
        vp = self.viewport().rect()
        if rect.isEmpty():
            return 1.0
        return min((vp.width() - 32) / rect.width(), (vp.height() - 32) / rect.height())

    def zoom_factor(self) -> float:
        return self.transform().m11()

    def zoom_by(self, factor: float) -> None:
        if not self.has_image():
            return
        cur = self.zoom_factor()
        lo = self.fit_scale() * 0.5
        new = max(lo, min(MAX_ZOOM, cur * factor))
        f = new / cur
        if abs(f - 1) < 1e-4:
            return
        self._fit = False
        self.scale(f, f)
        self.zoomChanged.emit()

    def zoom_to(self, scale: float, center: QPointF | None = None) -> None:
        self._fit = False
        self.resetTransform()
        self.scale(scale, scale)
        if center is not None:
            self.centerOn(center)
        self.zoomChanged.emit()

    # ------------------------------------------------------------ события
    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self._fit:
            self.fit()

    def wheelEvent(self, e: QWheelEvent) -> None:  # noqa: N802
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if self.wheel_zoom or ctrl:
            self._wheel_zoom(e)
        else:
            self.wheel_other(e)

    def _wheel_zoom(self, e: QWheelEvent) -> None:
        delta = e.angleDelta().y() or e.pixelDelta().y()
        if delta:
            self.zoom_by(1.0015 ** delta)
        e.accept()

    def wheel_other(self, e: QWheelEvent) -> None:
        e.ignore()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.fit()
        else:
            super().mouseDoubleClickEvent(e)

    def start_pan(self, pos: QPointF) -> None:
        self._panning = True
        self._pan_start = pos
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.MiddleButton or (
                e.button() == Qt.MouseButton.LeftButton and self.left_drag_pan):
            self.start_pan(e.position())
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._panning:
            d = e.position() - self._pan_start
            self._pan_start = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            self._fit = False
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._panning:
            self._panning = False
            self.viewport().unsetCursor()
            e.accept()
            return
        super().mouseReleaseEvent(e)
