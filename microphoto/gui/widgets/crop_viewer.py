"""Просмотр с окружностью поля зрения и ее правкой мышью.

Управление:
  • перетащить внутри круга — переместить круг;
  • перетащить за окружность (или за ручку) — изменить радиус;
  • колесо — радиус (Shift — точнее);
  • Ctrl + колесо — масштаб просмотра;
  • перетащить снаружи круга или средней кнопкой — сдвиг просмотра;
  • двойной щелчок — вписать в окно.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem

from ...core.models import Circle
from .image_viewer import ImageViewer

RING_TOL_PX = 9          # «захват» окружности в экранных пикселях
HANDLE_PX = 5
WHEEL_STEP = 0.004       # доля радиуса на один щелчок колеса
WHEEL_STEP_FINE = 0.001

COLOR_RING = QColor(255, 214, 10)        # контрастный желтый
COLOR_RING_ACTIVE = QColor(80, 220, 255)
COLOR_SHADOW = QColor(0, 0, 0, 170)
COLOR_CROSS = QColor(255, 60, 60)


class CircleItem(QGraphicsItem):
    def __init__(self) -> None:
        super().__init__()
        self.circle: Circle | None = None
        self.active = False
        self.dim_outside = True
        self.setZValue(5)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)

    def set_circle(self, c: Circle | None) -> None:
        self.prepareGeometryChange()
        self.circle = c
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        if self.circle is None:
            return QRectF()
        c = self.circle
        m = c.r * 0.1 + 200
        if self.dim_outside:
            return QRectF(-1e5, -1e5, 2e5, 2e5)
        return QRectF(c.x - c.r - m, c.y - c.r - m, 2 * (c.r + m), 2 * (c.r + m))

    def paint(self, p: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:
        c = self.circle
        if c is None:
            return
        lod = option.levelOfDetailFromTransform(p.worldTransform()) or 1.0
        px = 1.0 / lod      # один экранный пиксель в координатах сцены
        center = QPointF(c.x, c.y)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.dim_outside:
            # полупрозрачное затемнение снаружи — сразу видно, что попадет в результат
            path = QPainterPath()
            path.addRect(option.exposedRect)
            hole = QPainterPath()
            hole.addEllipse(center, c.r, c.r)
            p.fillPath(path.subtracted(hole), QColor(0, 0, 0, 90))

        shadow = QPen(COLOR_SHADOW, 4 * px)
        p.setPen(shadow)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(center, c.r, c.r)
        ring = QPen(COLOR_RING_ACTIVE if self.active else COLOR_RING, 2 * px)
        ring.setDashPattern([6, 4])
        p.setPen(ring)
        p.drawEllipse(center, c.r, c.r)

        # крест в центре
        s = 14 * px
        p.setPen(QPen(COLOR_SHADOW, 4 * px))
        p.drawLine(QPointF(c.x - s, c.y), QPointF(c.x + s, c.y))
        p.drawLine(QPointF(c.x, c.y - s), QPointF(c.x, c.y + s))
        p.setPen(QPen(COLOR_CROSS, 2 * px))
        p.drawLine(QPointF(c.x - s, c.y), QPointF(c.x + s, c.y))
        p.drawLine(QPointF(c.x, c.y - s), QPointF(c.x, c.y + s))

        # ручки радиуса
        hr = HANDLE_PX * px
        p.setPen(QPen(COLOR_SHADOW, 1.5 * px))
        p.setBrush(QBrush(COLOR_RING_ACTIVE if self.active else COLOR_RING))
        for ang in (0, 90, 180, 270):
            a = math.radians(ang)
            p.drawEllipse(QPointF(c.x + c.r * math.cos(a), c.y + c.r * math.sin(a)), hr, hr)


class CropViewer(ImageViewer):
    circleLive = Signal(object)                 # Circle — во время перетаскивания
    circleDragFinished = Signal(object, object, str)  # старый Circle, новый Circle, вид
    circleWheel = Signal(object)                # новый Circle от колеса

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.wheel_zoom = False         # колесо — радиус, Ctrl+колесо — масштаб
        self.left_drag_pan = False
        self.item = CircleItem()
        self.scene().addItem(self.item)
        self._mode: str | None = None
        self._start_circle: Circle | None = None
        self._grab = QPointF()
        self._grab_dr = 0.0
        self.editable = True
        self.setMouseTracking(True)

    def set_circle(self, c: Circle | None) -> None:
        if self._mode is not None:
            return        # во время перетаскивания круг меняет только мышь
        self.item.set_circle(c)

    def circle(self) -> Circle | None:
        return self.item.circle

    # ------------------------------------------------------------------
    def _hit(self, scene_pt: QPointF) -> str:
        c = self.item.circle
        if c is None or not self.editable:
            return "pan"
        d = math.hypot(scene_pt.x() - c.x, scene_pt.y() - c.y)
        tol = RING_TOL_PX / max(self.zoom_factor(), 1e-6)
        if abs(d - c.r) <= tol:
            return "resize"
        if d < c.r:
            return "move"
        return "pan"

    def _cursor_for(self, mode: str) -> Qt.CursorShape:
        return {
            "resize": Qt.CursorShape.SizeFDiagCursor,
            "move": Qt.CursorShape.SizeAllCursor,
        }.get(mode, Qt.CursorShape.OpenHandCursor if not self._fit_like() else Qt.CursorShape.ArrowCursor)

    def _fit_like(self) -> bool:
        return self.zoom_factor() <= self.fit_scale() * 1.01

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.has_image():
            sp = self.mapToScene(e.position().toPoint())
            mode = self._hit(sp)
            if mode in ("move", "resize"):
                c = self.item.circle
                self._mode = mode
                self._start_circle = c
                self._grab = sp - QPointF(c.x, c.y)
                self._grab_dr = math.hypot(sp.x() - c.x, sp.y() - c.y) - c.r
                self.item.active = True
                self.item.update()
                e.accept()
                return
            self.start_pan(e.position())
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._mode is not None:
            sp = self.mapToScene(e.position().toPoint())
            c = self.item.circle
            if self._mode == "move":
                nc = Circle(sp.x() - self._grab.x(), sp.y() - self._grab.y(), c.r)
            else:
                d = math.hypot(sp.x() - c.x, sp.y() - c.y) - self._grab_dr
                nc = Circle(c.x, c.y, max(10.0, d))
            self.item.set_circle(nc)
            self.circleLive.emit(nc)
            e.accept()
            return
        super().mouseMoveEvent(e)
        if not self._panning:
            sp = self.mapToScene(e.position().toPoint())
            self.viewport().setCursor(self._cursor_for(self._hit(sp)))

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._mode is not None and e.button() == Qt.MouseButton.LeftButton:
            mode = self._mode
            self._mode = None
            self.item.active = False
            self.item.update()
            start, end = self._start_circle, self.item.circle
            self._start_circle = None
            if start is not None and end is not None and start != end:
                self.circleDragFinished.emit(start, end, mode)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def wheel_other(self, e: QWheelEvent) -> None:
        c = self.item.circle
        if c is None or not self.editable or self._mode is not None:
            e.ignore()
            return
        delta = e.angleDelta().y() or e.angleDelta().x()   # Shift+колесо иногда «горизонтальное»
        if delta == 0:
            delta = e.pixelDelta().y() * 4    # тачпад
        if delta == 0:
            return
        step = WHEEL_STEP_FINE if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else WHEEL_STEP
        factor = (1 + step) ** (delta / 120)
        nc = Circle(c.x, c.y, max(10.0, c.r * factor))
        self.item.set_circle(nc)
        self.circleWheel.emit(nc)
        e.accept()
