"""Настройки: обработка (фон, резкость), масштабная шкала, экспорт.

Все изменения видны сразу в preview, а в проект попадают одной записью
истории (Undo) при нажатии «Применить».
"""

from __future__ import annotations

import logging

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core.constants import EXPORT_FORMATS, MAGNIFICATIONS
from ..core.cropper import apply_mask, crop_square
from ..core.image_loader import load_oriented
from ..core.models import (BACKGROUND_COLORS, SCALE_COLORS, SCALE_MARGINS, SCALE_POSITIONS, SCALE_SIZES,
                           CalibrationEntry, Circle, PhotoItem, ProcessingSettings, default_calibration)
from ..core.project_ops import default_circle
from ..core.scale_bar import draw_scale_bar
from ..workers.render_worker import pil_to_qimage
from .controller import ProjectController
from .media import MediaService
from .widgets.sharpen_preview import SharpenPreview
from .widgets.toggles import ToggleGroup

log = logging.getLogger(__name__)

PREVIEW_SIDE = 900

TAB_PROCESSING, TAB_SCALE, TAB_EXPORT = 0, 1, 2


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


def describe_change(old: ProcessingSettings, new: ProcessingSettings) -> str:
    """Понятная подпись для истории Undo."""
    parts = []
    if old.background_color != new.background_color:
        parts.append("Фон: " + BACKGROUND_COLORS[new.background_color].lower())
    if old.sharpen.to_dict() != new.sharpen.to_dict():
        parts.append("Резкость")
    if old.scale.color_mode != new.scale.color_mode:
        parts.append("Цвет шкалы")
    o, n = old.scale.to_dict(), new.scale.to_dict()
    o.pop("color_mode"), n.pop("color_mode")
    if o != n:
        parts.append("Масштабная шкала")
    if old.export.to_dict() != new.export.to_dict():
        parts.append("Экспорт")
    if len(parts) == 1:
        return parts[0]
    return "Изменение настроек"


class SettingsDialog(QDialog):
    def __init__(self, ctrl: ProjectController, media: MediaService, tab: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.ctrl = ctrl
        self.media = media
        self.s: ProcessingSettings = ctrl.settings.copy()
        self._loading = True
        self._base: Image.Image | None = None            # обрезка без фона, ~900 px (для шкалы)
        self._base_mask: Image.Image | None = None
        self._full_loaded = False                        # оригинал для просмотра резкости
        self.photo: PhotoItem | None = ctrl.current

        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_processing_tab(), "Обработка")
        self.tabs.addTab(self._build_scale_tab(), "Масштабная шкала")
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
        self.resize(1120, 740)
        self.tabs.setCurrentIndex(tab)
        self._tab_changed(self.tabs.currentIndex())
        self._update_scale_preview()

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
        self.color_combo = _combo(SCALE_COLORS)
        self.size_combo = _combo(SCALE_SIZES)
        self.margin_combo = _combo(SCALE_MARGINS)
        for c in (self.color_combo, self.pos_combo, self.size_combo, self.margin_combo):
            c.currentIndexChanged.connect(self._changed)
        fl.addRow("Цвет:", self.color_combo)
        fl.addRow("Положение:", self.pos_combo)
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

    # ---------------------------------------------------------------- обработка
    def _build_processing_tab(self) -> QWidget:
        w = QWidget()
        root = QHBoxLayout(w)
        left = QVBoxLayout()
        left_w = QWidget()
        left_w.setFixedWidth(330)
        left_w.setLayout(left)
        root.addWidget(left_w)

        bg = QGroupBox("Фон за пределами поля зрения")
        bl = QVBoxLayout(bg)
        self.bg_toggle = ToggleGroup([(k, v) for k, v in BACKGROUND_COLORS.items()])
        self.bg_toggle.valueChanged.connect(self._bg_clicked)
        bl.addWidget(self.bg_toggle)
        bl.addWidget(_note("Для всей партии. Цвет шкалы «Автоматически»: на черном фоне — белая, "
                           "на белом — черная."))
        left.addWidget(bg)

        sh = QGroupBox("Резкость")
        sl = QVBoxLayout(sh)
        self.sharp_enabled = QCheckBox("Повысить резкость")
        self.sharp_enabled.toggled.connect(self._changed)
        sl.addWidget(self.sharp_enabled)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setTickInterval(25)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setPageStep(10)
        self.slider.valueChanged.connect(self._changed)
        row.addWidget(self.slider, 1)
        self.slider_val = QLabel()
        self.slider_val.setMinimumWidth(44)
        self.slider_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider_val.setStyleSheet("font-weight: 600; font-size: 12pt;")
        row.addWidget(self.slider_val)
        sl.addLayout(row)
        ticks = QHBoxLayout()
        for text, align in (("0", Qt.AlignmentFlag.AlignLeft), ("50", Qt.AlignmentFlag.AlignHCenter),
                            ("100", Qt.AlignmentFlag.AlignRight)):
            t = QLabel(text)
            t.setObjectName("Hint")
            t.setAlignment(align)
            ticks.addWidget(t, 1)
        ticks.addSpacing(50)
        sl.addLayout(ticks)
        sl.addWidget(_note("50 — рекомендуемое значение, 100 — сильная резкость. Резкость применяется "
                           "только к изображению внутри поля зрения; фон и шкала остаются четкими."))
        left.addWidget(sh)
        left.addWidget(_note("Просмотр справа — текущее фото из оригинала. «100 %» — пиксель в пиксель. "
                             "Удерживайте «Оригинал» или пробел, чтобы временно увидеть исходное."))
        left.addStretch(1)

        right = QVBoxLayout()
        root.addLayout(right, 1)
        bar = QHBoxLayout()
        self.ba_toggle = ToggleGroup([("before", "До"), ("after", "После")])
        self.ba_toggle.setFixedWidth(180)
        self.ba_toggle.set_value("after")
        self.ba_toggle.valueChanged.connect(self._ba_clicked)
        bar.addWidget(self.ba_toggle)
        self.zoom100_btn = QPushButton("100 %")
        self.zoom100_btn.setObjectName("Toggle")
        self.zoom100_btn.setCheckable(True)
        self.zoom100_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.zoom100_btn.setToolTip("Пиксель в пиксель. Перетаскивайте мышью, чтобы смотреть другие участки.")
        self.zoom100_btn.toggled.connect(self._zoom100)
        bar.addWidget(self.zoom100_btn)
        bar.addStretch(1)
        self.hold_btn = QPushButton("Удерживайте — оригинал")
        self.hold_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hold_btn.pressed.connect(lambda: self.sharp_view.hold_original(True))
        self.hold_btn.released.connect(lambda: self.sharp_view.hold_original(False))
        bar.addWidget(self.hold_btn)
        right.addLayout(bar)
        self.sharp_view = SharpenPreview()
        self.sharp_view.setMinimumSize(480, 420)
        right.addWidget(self.sharp_view, 1)
        return w

    def _bg_clicked(self, key: str) -> None:
        self.bg_toggle.set_value(key)
        self._changed()

    def _ba_clicked(self, key: str) -> None:
        self.ba_toggle.set_value(key)
        self.sharp_view.set_show_after(key == "after")

    def _zoom100(self, on: bool) -> None:
        self.sharp_view.zoom_100(on)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Space and self.tabs.currentIndex() == TAB_PROCESSING:
            if not e.isAutoRepeat():
                self.sharp_view.hold_original(True)
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Space and self.tabs.currentIndex() == TAB_PROCESSING:
            if not e.isAutoRepeat():
                self.sharp_view.hold_original(False)
            return
        super().keyReleaseEvent(e)

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
        for combo, val in ((self.pos_combo, s.scale.position), (self.color_combo, s.scale.color_mode),
                           (self.size_combo, s.scale.size), (self.margin_combo, s.scale.margin)):
            combo.setCurrentIndex(max(0, combo.findData(val)))
        self.bg_toggle.set_value(s.background_color)
        self.sharp_enabled.setChecked(s.sharpen.enabled)
        self.slider.setValue(s.sharpen.amount)
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
        s.scale.color_mode = self.color_combo.currentData()
        s.scale.size = self.size_combo.currentData()
        s.scale.margin = self.margin_combo.currentData()
        s.sharpen.enabled = self.sharp_enabled.isChecked()
        s.sharpen.amount = self.slider.value()
        s.background_color = self.bg_toggle.value() or "black"
        s.export.format = self.fmt_combo.currentData()
        s.export.jpeg_quality = self.quality_spin.value()

    def _update_enabled(self) -> None:
        on = self.scale_enabled.isChecked()
        for wdg in (self.table, self.color_combo, self.pos_combo, self.size_combo, self.margin_combo):
            wdg.setEnabled(on)
        son = self.sharp_enabled.isChecked()
        self.slider.setEnabled(son)
        self.slider_val.setText(str(self.slider.value()) if son else "выкл.")
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
        if i == TAB_PROCESSING:
            self._ensure_full_crop()
            self._update_sharp_preview()
        elif i == TAB_SCALE:
            self._update_scale_preview()

    def accept(self) -> None:
        self._read_values()
        self.ctrl.set_settings(self.s, describe_change(self.ctrl.settings, self.s))
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
            base, mask = crop_square(img, c)
            if base.width > PREVIEW_SIDE:
                base = base.resize((PREVIEW_SIDE, PREVIEW_SIDE), Image.Resampling.LANCZOS)
                mask = mask.resize((PREVIEW_SIDE, PREVIEW_SIDE), Image.Resampling.BILINEAR)
            self._base, self._base_mask = base, mask
        except Exception:
            log.exception("Preview для настроек не построен")
            self._base = None

    def _update_scale_preview(self) -> None:
        if self._base is None:
            return
        img = apply_mask(self._base, self._base_mask, self.s.background_color)
        mag = self.preview_mag.currentData()
        if self.s.scale.enabled:
            img = draw_scale_bar(img, self.s.scale.calibration[mag], self.s.scale, self.s.background_color)
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
        if self._full_loaded or self.photo is None or self.photo.missing:
            return
        self._full_loaded = True
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            src = load_oriented(self.photo.source_path).image
            c = self.photo.circle or default_circle(src.width, src.height)
            crop, mask = crop_square(src, c)
            self.sharp_view.set_background(self.s.background_color)
            self.sharp_view.set_settings(self.s.sharpen)
            self.sharp_view.set_source(crop, mask)
        except Exception:
            log.exception("Просмотр резкости не построен")
            self.sharp_view.show_message("Не удалось открыть оригинал")
        finally:
            self.unsetCursor()

    def _update_sharp_preview(self) -> None:
        self.sharp_view.set_background(self.s.background_color)
        self.sharp_view.set_settings(self.s.sharpen)
