"""Справочные значения: режимы освещения, увеличения, калибровки по умолчанию."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LightMode:
    key: str
    title: str      # для интерфейса
    short: str      # для имени файла


LIGHT_MODES: tuple[LightMode, ...] = (
    LightMode("ppl", "Параллельные николи", "пп"),
    LightMode("xpl", "Скрещенные николи", "сп"),
    LightMode("refl", "Отраженный свет", "отраж"),
)
LIGHT_BY_KEY = {m.key: m for m in LIGHT_MODES}


@dataclass(frozen=True)
class Magnification:
    key: str
    title: str      # для интерфейса: «2,5×»
    short: str      # для имени файла: «2,5х» (кириллическая «х»)


MAGNIFICATIONS: tuple[Magnification, ...] = (
    Magnification("2.5", "2,5×", "2,5х"),
    Magnification("5", "5×", "5х"),
    Magnification("10", "10×", "10х"),
    Magnification("20", "20×", "20х"),
)
MAG_BY_KEY = {m.key: m for m in MAGNIFICATIONS}


# Экспериментальные калибровки: подпись шкалы и длина шкалы в долях
# диаметра поля зрения.
DEFAULT_CALIBRATION: dict[str, tuple[str, float]] = {
    "2.5": ("1 mm", 0.132),
    "5": ("1 mm", 0.218),
    "10": ("0.5 mm", 0.229),
    "20": ("0.25 mm", 0.2285),
}

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
HEIC_EXTENSIONS = {".heic", ".heif"}

EXPORT_FORMATS = {
    "jpg": ("JPG", ".jpg"),
    "tiff": ("TIFF (без потерь)", ".tif"),
    "png": ("PNG", ".png"),
}
