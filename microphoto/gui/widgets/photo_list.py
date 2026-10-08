"""Вертикальный список фотографий: миниатюра, номер, имя файла, статус."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QItemSelectionModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QListView, QMenu, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem)

from ...core import naming, project_ops
from .. import theme
from ..controller import ProjectController
from ..media import MediaService

ROW_H = 64
THUMB = 52

STATUS_COLORS = {
    project_ops.STATUS_EMPTY: theme.MUTED,
    project_ops.STATUS_PARAMS: "#2f6f3e",
    project_ops.STATUS_CIRCLE: theme.SUCCESS,
    project_ops.STATUS_DONE: theme.SUCCESS,
    project_ops.STATUS_ERROR: theme.ERROR,
    project_ops.STATUS_EXCLUDED: theme.MUTED,
    project_ops.STATUS_MISSING: theme.ERROR,
}

StatusRole = Qt.ItemDataRole.UserRole + 1
ThumbRole = Qt.ItemDataRole.UserRole + 2


class PhotoListModel(QAbstractListModel):
    def __init__(self, ctrl: ProjectController, media: MediaService, parent=None) -> None:
        super().__init__(parent)
        self.ctrl = ctrl
        self.media = media
        ctrl.projectLoaded.connect(self._reset)
        ctrl.photoListChanged.connect(self._reset)
        ctrl.photoChanged.connect(self._changed)
        ctrl.settingsChanged.connect(self._all_changed)
        media.thumbReady.connect(self._changed)

    def _reset(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def _changed(self, i: int) -> None:
        idx = self.index(i, 0)
        self.dataChanged.emit(idx, idx)

    def _all_changed(self) -> None:
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0))

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.ctrl.photos)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self.ctrl.photos[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return p.file_name
        if role == StatusRole:
            if self.media.error(index.row()):
                return project_ops.STATUS_ERROR
            return project_ops.photo_status(p)
        if role == ThumbRole:
            return self.media.thumbnail(index.row())
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [p.file_name]
            name = naming.output_file_name(p, self.ctrl.settings.export.format)
            if name:
                lines.append(f"Результат: {name}")
            err = self.media.error(index.row()) or p.export_error
            if err:
                lines.append(f"Ошибка: {err}")
            return "\n".join(lines)
        return None


class PhotoDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(200, ROW_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        card = r.adjusted(6, 2, -6, -2)
        if selected:
            painter.setPen(QPen(QColor(theme.ACCENT), 2))
            painter.setBrush(QColor(theme.ACCENT_SOFT))
            painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), 8, 8)
        elif hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f1f3f6"))
            painter.drawRoundedRect(card, 8, 8)

        # миниатюра
        tr = QRect(card.left() + 8, card.top() + (card.height() - THUMB) // 2, THUMB, THUMB)
        thumb: QImage | None = index.data(ThumbRole)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.VIEWER_BG))
        painter.drawRoundedRect(tr, 4, 4)
        if thumb is not None and not thumb.isNull():
            scaled = thumb.scaled(tr.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            x = tr.left() + (tr.width() - scaled.width()) // 2
            y = tr.top() + (tr.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)

        # текст
        left = tr.right() + 10
        text_w = card.right() - left - 6
        f = QFont(option.font)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(theme.TEXT))
        num = f"{index.row() + 1}."
        fm = painter.fontMetrics()
        nw = fm.horizontalAdvance(num + " ")
        painter.drawText(QRect(left, card.top() + 9, nw, 20), Qt.AlignmentFlag.AlignLeft, num)
        f.setBold(False)
        painter.setFont(f)
        name = painter.fontMetrics().elidedText(index.data(), Qt.TextElideMode.ElideMiddle, text_w - nw)
        painter.drawText(QRect(left + nw, card.top() + 9, text_w - nw, 20), Qt.AlignmentFlag.AlignLeft, name)

        status = index.data(StatusRole)
        sym, txt = project_ops.STATUS_TEXT.get(status, ("", ""))
        f2 = QFont(option.font)
        f2.setPointSizeF(max(7.5, f.pointSizeF() - 1))
        painter.setFont(f2)
        painter.setPen(QColor(STATUS_COLORS.get(status, theme.MUTED)))
        painter.drawText(QRect(left, card.top() + 32, text_w, 18), Qt.AlignmentFlag.AlignLeft, f"{sym} {txt}")
        painter.restore()


class PhotoListView(QListView):
    photoActivated = Signal(int)
    removeRequested = Signal(list)      # строки, которые нужно убрать из партии

    def __init__(self, ctrl: ProjectController, media: MediaService, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PhotoList")
        self.ctrl = ctrl
        self._model = PhotoListModel(ctrl, media, self)
        self.setModel(self._model)
        self.setItemDelegate(PhotoDelegate(self))
        # Ctrl/Shift + щелчок — выбрать несколько фото (например, чтобы убрать их из партии)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # стрелки обрабатывает окно
        self.selectionModel().currentChanged.connect(self._on_current)
        ctrl.currentChanged.connect(self.select_row)
        ctrl.projectLoaded.connect(lambda: self.select_row(ctrl.current_index))
        ctrl.photoListChanged.connect(lambda: self.select_row(ctrl.current_index))

    def selected_rows(self) -> list[int]:
        rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        if not rows and 0 <= self.ctrl.current_index < self._model.rowCount():
            rows = [self.ctrl.current_index]
        return rows

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        idx = self.indexAt(e.pos())
        if not idx.isValid():
            return
        if idx.row() not in self.selected_rows():
            self.setCurrentIndex(idx)
        rows = self.selected_rows()
        menu = QMenu(self)
        text = "Убрать из проекта" if len(rows) == 1 else f"Убрать из проекта ({len(rows)} фото)"
        act = menu.addAction(text)
        act.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        act.setToolTip("Файлы на диске не удаляются. Вернуть — Ctrl+Z")
        if menu.exec(e.globalPos()) is act:
            self.removeRequested.emit(rows)

    def _on_current(self, cur: QModelIndex, _prev: QModelIndex) -> None:
        if cur.isValid() and cur.row() != self.ctrl.current_index:
            self.photoActivated.emit(cur.row())

    def select_row(self, row: int) -> None:
        if not (0 <= row < self._model.rowCount()):
            return
        idx = self._model.index(row, 0)
        if self.currentIndex() != idx:
            # переход к другому фото из программы (Enter, стрелки, Undo) — выделено только оно;
            # щелчки мышью с Ctrl/Shift меняют текущую строку сами и сюда не попадают
            self.selectionModel().setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)
