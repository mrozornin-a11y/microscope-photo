"""Формирование имени файла результата."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import EXPORT_FORMATS, LIGHT_BY_KEY, MAG_BY_KEY
from .models import PhotoItem

_INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def sanitize(text: str) -> str:
    """Убирает недопустимые в Windows символы."""
    text = _INVALID.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip(". ")
    if text.upper() in _RESERVED:
        text = f"_{text}"
    return text


def output_stem(photo: PhotoItem) -> str | None:
    """Номер_НазваниеШлифа_Режим_Увеличение — или None, если параметры не заданы."""
    if not photo.params_complete():
        return None
    name = sanitize(photo.sample_name) or "без_названия"
    light = LIGHT_BY_KEY[photo.light_mode].short
    mag = MAG_BY_KEY[photo.magnification].short
    return f"{photo.photo_number}_{name}_{light}_{mag}"


def output_file_name(photo: PhotoItem, fmt: str) -> str | None:
    stem = output_stem(photo)
    if stem is None:
        return None
    return stem + EXPORT_FORMATS[fmt][1]


def duplicate_name(file_name: str, n: int) -> str:
    p = Path(file_name)
    return f"{p.stem}__повтор_{n}{p.suffix}"


def output_folder(photo: PhotoItem) -> str | None:
    """Папка результата: называется именем шлифа (все фото шлифа — в одной папке)."""
    if not photo.sample_name.strip():
        return None
    return sanitize(photo.sample_name) or "без_названия"


def output_relpath(photo: PhotoItem, fmt: str) -> Path | None:
    """Путь результата относительно папки результата: «Шлиф/Номер_Шлиф_Режим_Увеличение.ext»."""
    name = output_file_name(photo, fmt)
    folder = output_folder(photo)
    if name is None or folder is None:
        return None
    return Path(folder) / name


def output_display(photo: PhotoItem, fmt: str) -> str | None:
    rel = output_relpath(photo, fmt)
    return None if rel is None else f"{rel.parent.name}\\{rel.name}"
