"""Настройки: масштабная шкала (калибровка и внешний вид), резкость, экспорт.

Все изменения видны сразу в preview, а в проект попадают одной записью
истории (Undo) при нажатии «Применить».
"""

from __future__ import annotations

import logging

from PIL import Image
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core.constants import EXPORT_FORMATS, MAGNIFICATIONS
from ..core.cropper import crop_circle
from ..core.image_loader import load_oriented
from ..core.models import (SCALE_MARGINS, SCALE_POSITIONS, SCALE_SIZES, SCALE_STYLES, CalibrationEntry, Circle,
                           PhotoItem, ProcessingSettings, default_calibration)
from ..core.project_ops import default_circle
from ..core.scale_bar import draw_scale_bar
from ..core.sharpness import SHARPENERS, sharpen
from ..workers.render_worker import pil_to_qimage
from .controller import ProjectController
from .media import MediaService

log = logging.getLogger(__name__)

PREVIEW_SIDE = 900
FRAGMENT = 320


def _combo(options: dict[str, str]) -> QComboBox:
    c = QComboBox()
    for k, v in options.items():
        c.addItem(v, k)
    return c


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Hint")
    lbl.setWordWrap(True)
    return lbl


class _PickLabel(QLabel):
    """Миниатюра с рамкой выбранного фрагмента; щелчок выбирает фрагмент."""

    picked = Signal(float, float)    # доли 0…1

    def __init__(self) -> None:
        super().__init__()
        self.frac_rect: tuple[float, float, float, float] | None = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return
        ox = (self.width() - pm.width()) / 2
        oy = (self.height() - pm.height()) / 2
        fx = (e.position().x() - ox) / pm.width()
        fy = (e.position().y() - oy) / pm.height()
        if 0 <= fx <= 1 and 0 <= fy <= 1:
            self.picked.emit(fx, fy)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        pm = self.pixmap()
        if self.frac_rect is None or pm is None or pm.isNull():
            return
        ox = (self.width() - pm.width()) / 2
        oy = (self.height() - pm.height()) / 2
        x, y, w, h = self.frac_rect
        p = QPainter(self)
        p.setPen(QPen(QColor(255, 214, 10), 2))
        p.drawRect(QRect(int(ox + x * pm.width()), int(oy + y * pm.height()),
                         max(4, int(w * pm.width())), max(4, int(h * pm.height()))))
        p.end()


class SettingsDialog(QDialog):
    def __init__(self, ctrl: ProjectController, media: MediaService, tab: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.ctrl = ctrl
        self.media = media
        self.s: ProcessingSettings = ctrl.settings.copy()
        self._loading = True
        self._base: Image.Image | None = None            # обрезанное, без резкости, ~900 px
        self._full_crop: Image.Image | None = None       # обрезанное в полном разрешении (для 100 %)
        self._frag_center = (0.5, 0.5)
        self.photo: PhotoItem | None = ctrl.current

        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_scale_tab(), "Масштабная шкала")
        self.tabs.addTab(self._build_sharp_tab(), "Резкость")
        self.tabs.addTab(self._build_export_tab(), "Экспорт")
        self.tabs.currentChanged.connect(self._tab_changed)
        lay.addWidget(self.tabs, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        bb.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self._load_values()
        self._loading = False
        self._prepare_base()
        self.tabs.setCurrentIndex(tab)
        self._update_scale_preview()
        self.resize(1080, 700)

    # ---------------------------------------------------------------- шкала
    def _build_scale_tab(self) -> QWidget:
        w = QWidget()
        root = QHBoxLayout(w)
        left = QVBoxLayout()
        root.addLayout(left, 1)

        self.scale_enabled = QCheckBox("Добавлять масштабную шкалу")
        self.scale_enabled.toggled.connect(self._changed)
        left.addWidget(self.scale_enabled)

        cal = QGroupBox("1. Калибровка")
        cl = QVBoxLayout(cal)
        cl.addWidget(_note("Определяет физический размер шкалы. Длина шкалы — доля диаметра "
                           "найденного поля зрения (не размера фотографии)."))
        self.table = QTableWidget(len(MAGNIFICATIONS), 3)
        self.table.setHorizontalHeaderLabels(["Увеличение", "Подпись", "Доля диаметра"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self._frac_spins: dict[str, QDoubleSpinBox] = {}
        for row, m in enumerate(MAGNIFICATIONS):
            it = QTableWidgetItem(m.title)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 0, it)
            self.table.setItem(row, 1, QTableWidgetItem(""))
            sp = QDoubleSpinBox()
            sp.setDecimals(2)
            sp.setRange(1.0, 90.0)
            sp.setSingleStep(0.1)
            sp.setSuffix(" %")
            sp.valueChanged.connect(self._changed)
            self._frac_spins[m.key] = sp
            self.table.setCellWidget(row, 2, sp)
            self.table.setRowHeight(row, 34)
        self.table.itemChanged.connect(self._changed)
        self.table.setFixedHeight(34 * len(MAGNIFICATIONS) + self.table.horizontalHeader().height() + 6)
        cl.addWidget(self.table)
        reset = QPushButton("Восстановить значения по умолчанию")
        reset.clicked.connect(self._reset_calibration)
        cl.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        left.addWidget(cal)

        look = QGroupBox("2. Внешний вид")
        fl = QFormLayout(look)
        fl.addRow(_note("Только оформление — на размер шкалы не влияет."))
        self.pos_combo = _combo(SCALE_POSITIONS)
        self.style_combo = _combo(SCALE_STYLES)
        self.size_combo = _combo(SCALE_SIZES)
        self.margin_combo = _combo(SCALE_MARGINS)
        for c in (self.pos_combo, self.style_combo, self.size_combo, self.margin_combo):
            c.currentIndexChanged.connect(self._changed)
        fl.addRow("Положение:", self.pos_combo)
        fl.addRow("Стиль:", self.style_combo)
        fl.addRow("Размер:", self.size_combo)
        fl.addRow("Отступ от края:", self.margin_combo)
        left.addWidget(look)
        left.addStretch(1)

        right = QVBoxLayout()
        root.addLayout(right, 1)
        top = QHBoxLayout()
        top.addWidget(QLabel("Пример на текущем фото, увеличение:"))
        self.preview_mag = QComboBox()
        for m in MAGNIFICATIONS:
            self.preview_mag.addItem(m.title, m.key)
        mag = (self.photo.magnification if self.photo and self.photo.magnification else "10")
        self.preview_mag.setCurrentIndex(self.preview_mag.findData(mag))
        self.preview_mag.currentIndexChanged.connect(self._update_scale_preview)
        top.addWidget(self.preview_mag)
        top.addStretch(1)
        right.addLayout(top)
        self.scale_preview = QLabel()
        self.scale_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scale_preview.setMinimumSize(420, 420)
        self.scale_preview.setStyleSheet("background: #1b1c1f; border-radius: 8px;")
        right.addWidget(self.scale_preview, 1)
        self.scale_zoom = QLabel()
        self.scale_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scale_zoom.setStyleSheet("background: #1b1c1f; border-radius: 8px;")
        self.scale_zoom.setFixedHeight(130)
        right.addWidget(self.scale_zoom)
        return w

    # ---------------------------------------------------------------- резкость
    def _build_sharp_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        top = QHBoxLayout()
        self.sharp_enabled = QCheckBox("Повысить резкость")
        self.sharp_enabled.toggled.connect(self._changed)
        top.addWidget(self.sharp_enabled)
        top.addSpacing(20)
        top.addWidget(QLabel("0 %"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setTickInterval(25)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setPageStep(10)
        self.slider.setMinimumWidth(300)
        self.slider.valueChanged.connect(self._changed)
        top.addWidget(self.slider, 1)
        top.addWidget(QLabel("+100 %"))
        self.slider_val = QLabel()
        self.slider_val.setMinimumWidth(60)
        self.slider_val.setStyleSheet("font-weight: 600;")
        top.addWidget(self.slider_val)
        root.addLayout(top)
        row = QHBoxLayout()
        row.addWidget(QLabel("Метод:"))
        self.method_combo = QComboBox()
        for k, sh in SHARPENERS.items():
            self.method_combo.addItem(sh.title, k)
        self.method_combo.currentIndexChanged.connect(self._changed)
        row.addWidget(self.method_combo)
        row.addStretch(1)
        root.addLayout(row)
        root.addWidget(_note("Резкость применяется после обрезки и до нанесения шкалы. "
                             "Ниже — фрагмент текущего фото в масштабе 100 % (из оригинала). "
                             "Щелкните по миниатюре, чтобы выбрать другой участок."))
        cmp = QHBoxLayout()
        self.pick = _PickLabel()
        self.pick.setFixedSize(220, 220)
        self.pick.setStyleSheet("background: #1b1c1f; border-radius: 8px;")
        self.pick.picked.connect(self._pick_fragment)
        cmp.addWidget(self.pick, 0, Qt.AlignmentFlag.AlignTop)
        for title, attr in (("Исходное", "frag_before"), ("После обработки", "frag_after")):
            col = QVBoxLayout()
            t = QLabel(title)
            t.setStyleSheet("font-weight: 600;")
            col.addWidget(t)
            lbl = QLabel()
            lbl.setFixedSize(FRAGMENT, FRAGMENT)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("background: #1b1c1f; border-radius: 8px;")
            col.addWidget(lbl)
            col.addStretch(1)
            setattr(self, attr, lbl)
            cmp.addLayout(col)
        cmp.addStretch(1)
        root.addLayout(cmp)
        root.addStretch(1)
        return w

    # ---------------------------------------------------------------- экспорт
    def _build_export_tab(self) -> QWidget:
        w = QWidget()
        fl = QFormLayout(w)
        self.fmt_combo = QComboBox()
        for k, (title, _ext) in EXPORT_FORMATS.items():
            self.fmt_combo.addItem(title, k)
        self.fmt_combo.currentIndexChanged.connect(self._changed)
        fl.addRow("Формат файлов:", self.fmt_combo)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(50, 100)
        self.quality_spin.valueChanged.connect(self._changed)
        fl.addRow("Качество JPEG:", self.quality_spin)
        fl.addRow(_note("TIFF сохраняется без потерь (сжатие Deflate). Исходные файлы никогда не "
                        "изменяются — результат всегда создается заново из оригиналов."))
        return w

    # ---------------------------------------------------------------- значения
    def _load_values(self) -> None:
        s = self.s
        self.scale_enabled.setChecked(s.scale.enabled)
        for row, m in enumerate(MAGNIFICATIONS):
            cal = s.scale.calibration[m.key]
            self.table.item(row, 1).setText(cal.label)
            self._frac_spins[m.key].setValue(cal.fraction * 100)
        for combo, val in ((self.pos_combo, s.scale.position), (self.style_combo, s.scale.style),
                           (self.size_combo, s.scale.size), (self.margin_combo, s.scale.margin)):
            combo.setCurrentIndex(max(0, combo.findData(val)))
        self.sharp_enabled.setChecked(s.sharpen.enabled)
        self.slider.setValue(s.sharpen.amount)
        self.method_combo.setCurrentIndex(max(0, self.method_combo.findData(s.sharpen.method)))
        self.fmt_combo.setCurrentIndex(max(0, self.fmt_combo.findData(s.export.format)))
        self.quality_spin.setValue(s.export.jpeg_quality)
        self._update_enabled()

    def _read_values(self) -> None:
        s = self.s
        s.scale.enabled = self.scale_enabled.isChecked()
        for row, m in enumerate(MAGNIFICATIONS):
            label = (self.table.item(row, 1).text() if self.table.item(row, 1) else "").strip()
            if not label:
                label = s.scale.calibration[m.key].label
            s.scale.calibration[m.key] = CalibrationEntry(label, round(self._frac_spins[m.key].value() / 100, 6))
        s.scale.position = self.pos_combo.currentData()
        s.scale.style = self.style_combo.currentData()
        s.scale.size = self.size_combo.currentData()
        s.scale.margin = self.margin_combo.currentData()
        s.sharpen.enabled = self.sharp_enabled.isChecked()
        s.sharpen.amount = self.slider.value()
        s.sharpen.method = self.method_combo.currentData()
        s.export.format = self.fmt_combo.currentData()
        s.export.jpeg_quality = self.quality_spin.value()

    def _update_enabled(self) -> None:
        on = self.scale_enabled.isChecked()
        for wdg in (self.table, self.pos_combo, self.style_combo, self.size_combo, self.margin_combo):
            wdg.setEnabled(on)
        son = self.sharp_enabled.isChecked()
        self.slider.setEnabled(son)
        self.method_combo.setEnabled(son)
        self.slider_val.setText(f"+{self.slider.value()} %" if son else "выкл.")
        self.quality_spin.setEnabled(self.fmt_combo.currentData() == "jpg")

    def _changed(self, *_args) -> None:
        if self._loading:
            return
        self._read_values()
        self._update_enabled()
        self._update_scale_preview()
        self._update_sharp_preview()

    def _reset_calibration(self) -> None:
        self._loading = True
        for row, m in enumerate(MAGNIFICATIONS):
            cal = default_calibration()[m.key]
            self.table.item(row, 1).setText(cal.label)
            self._frac_spins[m.key].setValue(cal.fraction * 100)
        self._loading = False
        self._changed()

    def _tab_changed(self, i: int) -> None:
        if i == 1:
            self._ensure_full_crop()
            self._update_sharp_preview()

    def accept(self) -> None:
        self._read_values()
        self.ctrl.set_settings(self.s, "Изменение настроек")
        super().accept()

    # ---------------------------------------------------------------- preview
    def _photo_circle(self, w: int, h: int, full_w: int) -> Circle:
        p = self.photo
        k = w / full_w if full_w else 1.0
        if p is not None and p.circle is not None:
            return p.circle.scaled(k)
        return default_circle(w, h)

    def _prepare_base(self) -> None:
        p = self.photo
        path = self.media.preview_path(self.ctrl.current_index) if p is not None else None
        if p is None or path is None or not p.width:
            self.scale_preview.setText("Нет фотографии для примера")
            return
        try:
            with Image.open(path) as im:
                img = im.convert("RGB")
            c = self._photo_circle(img.width, img.height, p.width)
            base, _mask = crop_circle(img, c)
            if base.width > PREVIEW_SIDE:
                base = base.resize((PREVIEW_SIDE, PREVIEW_SIDE), Image.Resampling.LANCZOS)
            self._base = base
        except Exception:
            log.exception("Preview для настроек не построен")
            self._base = None

    def _update_scale_preview(self) -> None:
        if self._base is None:
            return
        img = self._base
        mag = self.preview_mag.currentData()
        if self.s.scale.enabled:
            img = draw_scale_bar(img, self.s.scale.calibration[mag], self.s.scale)
        pm = QPixmap.fromImage(pil_to_qimage(img))
        side = min(self.scale_preview.width(), self.scale_preview.height()) - 12
        side = max(200, side)
        self.scale_preview.setPixmap(pm.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        # увеличенный угол со шкалой
        W = img.width
        if self.s.scale.position == "left":
            box = (0, int(W * 0.78), int(W * 0.5), W)
        else:
            box = (int(W * 0.5), int(W * 0.78), W, W)
        corner = img.crop(box)
        cpm = QPixmap.fromImage(pil_to_qimage(corner))
        self.scale_zoom.setPixmap(cpm.scaled(self.scale_zoom.width() - 12, self.scale_zoom.height() - 12,
                                             Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._update_scale_preview()

    def _ensure_full_crop(self) -> None:
        if self._full_crop is not None or self.photo is None or self.photo.missing:
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            src = load_oriented(self.photo.source_path).image
            c = self.photo.circle or default_circle(src.width, src.height)
            self._full_crop, _ = crop_circle(src, c)
            thumb = self._full_crop.copy()
            thumb.thumbnail((210, 210))
            self.pick.setPixmap(QPixmap.fromImage(pil_to_qimage(thumb)))
        except Exception:
            log.exception("Фрагмент 100% не построен")
            self.frag_before.setText("Не удалось открыть оригинал")
        finally:
            self.unsetCursor()

    def _pick_fragment(self, fx: float, fy: float) -> None:
        self._frag_center = (fx, fy)
        self._update_sharp_preview()

    def _update_sharp_preview(self) -> None:
        if self._full_crop is None:
            return
        img = self._full_crop
        W = img.width
        half = FRAGMENT // 2
        cx = int(self._frag_center[0] * W)
        cy = int(self._frag_center[1] * W)
        cx = min(max(cx, half), W - half)
        cy = min(max(cy, half), W - half)
        pad = 4      # резкость считается по соседям — берем с запасом
        box = (cx - half - pad, cy - half - pad, cx + half + pad, cy + half + pad)
        region = img.crop(box)
        after = sharpen(region, self.s.sharpen)
        inner = (pad, pad, pad + FRAGMENT, pad + FRAGMENT)
        self.frag_before.setPixmap(QPixmap.fromImage(pil_to_qimage(region.crop(inner))))
        self.frag_after.setPixmap(QPixmap.fromImage(pil_to_qimage(after.crop(inner))))
        self.pick.frac_rect = ((cx - half) / W, (cy - half) / W, FRAGMENT / W, FRAGMENT / W)
        self.pick.update()

