"""Поиск фотографий в папке и сортировка по времени съемки."""

from __future__ import annotations

import re
from pathlib import Path

from .exif_utils import capture_time
from .image_loader import is_supported
from .models import PhotoItem


def natural_key(text: str):
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]


def find_images(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    return [p for p in folder.iterdir() if p.is_file() and is_supported(p) and not p.name.startswith("._")]


def sort_key(item: PhotoItem):
    return (item.capture_time or 0.0, natural_key(item.file_name))


def scan_folder(folder: str | Path) -> list[PhotoItem]:
    """Список фотографий папки, отсортированный по EXIF-времени съемки."""
    items = []
    for p in find_images(folder):
        ts, from_exif = capture_time(p)
        items.append(PhotoItem(source_path=str(p), capture_time=ts, capture_from_exif=from_exif))
    items.sort(key=sort_key)
    return items


def merge_rescan(saved: list[PhotoItem], folder: str | Path) -> list[PhotoItem]:
    """Объединяет сохраненную разметку с текущим содержимым папки.

    Известные файлы сохраняют свою разметку, новые добавляются по дате,
    пропавшие помечаются как отсутствующие (разметка не теряется).
    """
    by_path = {Path(p.source_path).resolve().as_posix().casefold(): p for p in saved}
    result: list[PhotoItem] = []
    seen = set()
    try:
        fresh = scan_folder(folder)
    except OSError:
        fresh = []
    for item in fresh:
        key = Path(item.source_path).resolve().as_posix().casefold()
        seen.add(key)
        old = by_path.get(key)
        result.append(old if old is not None else item)
    for key, old in by_path.items():
        if key not in seen:
            old.missing = True
            result.append(old)
    # Сохраняем прежний порядок известных файлов; новые — по времени.
    result.sort(key=sort_key)
    return result
