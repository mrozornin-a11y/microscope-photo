"""Модель данных: фотография, настройки обработки, проект (партия фотографий).

Модель не зависит от Qt. GUI только читает и изменяет её через контроллер.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .constants import DEFAULT_CALIBRATION, LIGHT_BY_KEY, MAG_BY_KEY


@dataclass(frozen=True)
class Circle:
    """Окружность поля зрения в координатах исходного (повернутого по EXIF) изображения."""

    x: float
    y: float
    r: float

    def scaled(self, k: float) -> "Circle":
        return Circle(self.x * k, self.y * k, self.r * k)

    def to_list(self) -> list[float]:
        return [round(self.x, 2), round(self.y, 2), round(self.r, 2)]

    @staticmethod
    def from_list(v: Any) -> "Circle | None":
        if not v or len(v) != 3:
            return None
        try:
            x, y, r = (float(a) for a in v)
        except (TypeError, ValueError):
            return None
        if r <= 0:
            return None
        return Circle(x, y, r)


# Поля фотографии, которые редактирует пользователь (и которые попадают в Undo).
EDITABLE_FIELDS = (
    "sample_name",
    "light_mode",
    "magnification",
    "photo_number",
    "circle",
    "circle_source",
    "circle_confirmed",
    "excluded",
)


@dataclass
class PhotoItem:
    source_path: str
    capture_time: float | None = None        # unix time
    capture_from_exif: bool = False
    width: int = 0                            # размер после поворота по EXIF
    height: int = 0
    # «Отпечаток» исходного файла: разметка из сохраненного проекта переносится
    # только на тот же самый файл (а не на другой файл с тем же именем)
    file_size: int = 0
    file_mtime_ns: int = 0
    file_head: str = ""                       # sha1 первых 64 КБ файла

    sample_name: str = ""
    light_mode: str | None = None             # ключ из LIGHT_MODES
    magnification: str | None = None          # ключ из MAGNIFICATIONS
    photo_number: int | None = None

    circle: Circle | None = None
    circle_source: str = ""                   # auto / default / manual / previous / series
    circle_confirmed: bool = False
    detect_confidence: float | None = None

    excluded: bool = False

    export_status: str = ""                   # "" / done / error
    export_error: str = ""
    output_path: str = ""
    output_signature: list[float] = field(default_factory=list)   # [size, mtime] записанного файла

    # Только во время работы программы
    missing: bool = field(default=False, compare=False)

    @property
    def path(self) -> Path:
        return Path(self.source_path)

    @property
    def file_name(self) -> str:
        return self.path.name

    def params_complete(self) -> bool:
        return (
            bool(self.sample_name.strip())
            and self.light_mode in LIGHT_BY_KEY
            and self.magnification in MAG_BY_KEY
            and self.photo_number is not None
        )

    def params_empty(self) -> bool:
        return (
            not self.sample_name.strip()
            and self.light_mode is None
            and self.magnification is None
            and self.photo_number is None
        )

    def editable_values(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in EDITABLE_FIELDS}

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("missing", None)
        d["circle"] = self.circle.to_list() if self.circle else None
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PhotoItem":
        known = {f.name for f in fields(PhotoItem)} - {"missing"}
        kwargs = {k: v for k, v in d.items() if k in known}
        kwargs["circle"] = Circle.from_list(d.get("circle"))
        item = PhotoItem(**kwargs)
        if item.light_mode not in LIGHT_BY_KEY:
            item.light_mode = None
        if item.magnification not in MAG_BY_KEY:
            item.magnification = None
        if item.photo_number is not None:
            try:
                item.photo_number = int(item.photo_number)
            except (TypeError, ValueError):
                item.photo_number = None
        item.sample_name = str(item.sample_name or "")
        try:
            item.file_size = int(item.file_size or 0)
            item.file_mtime_ns = int(item.file_mtime_ns or 0)
        except (TypeError, ValueError):
            item.file_size, item.file_mtime_ns = 0, 0
        item.file_head = str(item.file_head or "")
        return item

    def has_fingerprint(self) -> bool:
        return self.file_size > 0 and self.file_mtime_ns > 0


# ---------------------------------------------------------------- настройки

SCALE_POSITIONS = {"right": "Справа снизу", "left": "Слева снизу"}
SCALE_COLORS = {
    "auto": "Автоматически (по цвету фона)",
    "white": "Белый",
    "black": "Черный",
}
BACKGROUND_COLORS = {"black": "Черный", "white": "Белый"}
SCALE_SIZES = {"small": "Маленький", "normal": "Обычный", "large": "Крупный"}
SCALE_MARGINS = {"small": "Меньше", "normal": "Обычный", "large": "Больше"}


@dataclass
class CalibrationEntry:
    label: str
    fraction: float


def default_calibration() -> dict[str, CalibrationEntry]:
    return {k: CalibrationEntry(lbl, frac) for k, (lbl, frac) in DEFAULT_CALIBRATION.items()}


@dataclass
class ScaleSettings:
    enabled: bool = True
    calibration: dict[str, CalibrationEntry] = field(default_factory=default_calibration)
    position: str = "right"
    color_mode: str = "auto"    # auto: черный фон → белая шкала, белый фон → черная
    size: str = "normal"
    margin: str = "normal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "calibration": {k: [v.label, v.fraction] for k, v in self.calibration.items()},
            "position": self.position,
            "color_mode": self.color_mode,
            "size": self.size,
            "margin": self.margin,
        }

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> "ScaleSettings":
        s = ScaleSettings()
        if not isinstance(d, dict):
            return s
        s.enabled = bool(d.get("enabled", s.enabled))
        cal = d.get("calibration")
        if isinstance(cal, dict):
            for k in s.calibration:
                v = cal.get(k)
                try:
                    label, frac = str(v[0]), float(v[1])
                    if 0 < frac < 1 and label.strip():
                        s.calibration[k] = CalibrationEntry(label, frac)
                except (TypeError, ValueError, IndexError):
                    pass
        if d.get("position") in SCALE_POSITIONS:
            s.position = d["position"]
        if d.get("color_mode") in SCALE_COLORS:
            s.color_mode = d["color_mode"]
        elif d.get("style") == "black":
            # старые проекты: «white» был значением по умолчанию → теперь «auto»
            s.color_mode = "black"
        if d.get("size") in SCALE_SIZES:
            s.size = d["size"]
        if d.get("margin") in SCALE_MARGINS:
            s.margin = d["margin"]
        return s


@dataclass
class SharpenSettings:
    enabled: bool = True
    amount: int = 50            # пользовательская шкала 0 … 100 (см. core/sharpness.py)
    method: str = "usm"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> "SharpenSettings":
        s = SharpenSettings()
        if isinstance(d, dict):
            s.enabled = bool(d.get("enabled", s.enabled))
            try:
                s.amount = max(0, min(100, int(d.get("amount", s.amount))))
            except (TypeError, ValueError):
                pass
            method = str(d.get("method", s.method))
            # прежний слабый алгоритм Pillow Sharpness больше не используется
            s.method = "usm" if method == "pillow" else method
        return s


@dataclass
class ExportSettings:
    format: str = "jpg"         # jpg / tiff / png
    jpeg_quality: int = 95

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> "ExportSettings":
        s = ExportSettings()
        if isinstance(d, dict):
            if d.get("format") in ("jpg", "tiff", "png"):
                s.format = d["format"]
            try:
                s.jpeg_quality = max(50, min(100, int(d.get("jpeg_quality", s.jpeg_quality))))
            except (TypeError, ValueError):
                pass
        return s


@dataclass
class ProcessingSettings:
    """Всё, что влияет на результат, но не на разметку фотографий."""

    scale: ScaleSettings = field(default_factory=ScaleSettings)
    sharpen: SharpenSettings = field(default_factory=SharpenSettings)
    export: ExportSettings = field(default_factory=ExportSettings)
    background_color: str = "black"     # фон за пределами поля зрения: black / white

    def copy(self) -> "ProcessingSettings":
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale.to_dict(),
            "sharpen": self.sharpen.to_dict(),
            "export": self.export.to_dict(),
            "background_color": self.background_color,
        }

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> "ProcessingSettings":
        d = d if isinstance(d, dict) else {}
        return ProcessingSettings(
            scale=ScaleSettings.from_dict(d.get("scale")),
            sharpen=SharpenSettings.from_dict(d.get("sharpen")),
            export=ExportSettings.from_dict(d.get("export")),
            background_color=d.get("background_color") if d.get("background_color") in BACKGROUND_COLORS
            else "black",
        )


@dataclass
class Project:
    """Одна партия фотографий (одна исходная папка)."""

    source_dir: str = ""
    output_dir: str = ""
    photos: list[PhotoItem] = field(default_factory=list)
    settings: ProcessingSettings = field(default_factory=ProcessingSettings)
    current_index: int = 0
    stage: int = 0                  # 0 — фотографии, 1 — поле зрения, 2 — готово
    finished: bool = False          # экспорт выполнен и после него ничего не меняли
    name_list: list[str] = field(default_factory=list)
    # фото, убранные из партии (файлы на диске не тронуты) — не возвращать при пересканировании
    removed_paths: list[str] = field(default_factory=list)
    # отпечатки убранных файлов [размер, mtime_ns]: другой файл с тем же именем — уже новое фото
    removed_fp: dict[str, list[int]] = field(default_factory=dict)
    saved_at: float = 0.0           # время последнего сохранения (unix)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "source_dir": self.source_dir,
            "output_dir": self.output_dir,
            "current_index": self.current_index,
            "stage": self.stage,
            "finished": self.finished,
            "name_list": list(self.name_list),
            "removed_paths": list(self.removed_paths),
            "removed_fp": dict(self.removed_fp),
            "saved_at": self.saved_at,
            "settings": self.settings.to_dict(),
            "photos": [p.to_dict() for p in self.photos],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Project":
        p = Project(
            source_dir=str(d.get("source_dir", "")),
            output_dir=str(d.get("output_dir", "")),
            settings=ProcessingSettings.from_dict(d.get("settings")),
            stage=int(d.get("stage", 0)) if str(d.get("stage", 0)).isdigit() else 0,
            finished=bool(d.get("finished", False)),
            name_list=[str(x) for x in d.get("name_list", []) if str(x).strip()],
            removed_paths=[str(x) for x in d.get("removed_paths", []) if str(x).strip()],
        )
        rfp = d.get("removed_fp")
        if isinstance(rfp, dict):
            for k, v in rfp.items():
                try:
                    p.removed_fp[str(k)] = [int(v[0]), int(v[1])]
                except (TypeError, ValueError, IndexError):
                    pass
        try:
            p.saved_at = float(d.get("saved_at", 0) or 0)
        except (TypeError, ValueError):
            p.saved_at = 0.0
        photos = []
        for pd in d.get("photos", []):
            if isinstance(pd, dict) and pd.get("source_path"):
                photos.append(PhotoItem.from_dict(pd))
        p.photos = photos
        try:
            p.current_index = max(0, min(int(d.get("current_index", 0)), max(0, len(photos) - 1)))
        except (TypeError, ValueError):
            p.current_index = 0
        p.stage = max(0, min(2, p.stage))
        return p
