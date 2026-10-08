"""Поиск фотографий в папке и сортировка по времени съемки."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path

from .exif_utils import capture_time
from .image_loader import is_supported
from .models import PhotoItem

log = logging.getLogger(__name__)

HEAD_BYTES = 64 * 1024
LEGACY_TIME_TOL = 1.5      # секунды


def natural_key(text: str):
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]


def find_images(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    return [p for p in folder.iterdir() if p.is_file() and is_supported(p) and not p.name.startswith("._")]


def sort_key(item: PhotoItem):
    return (item.capture_time or 0.0, natural_key(item.file_name))


def file_fingerprint(path: str | Path) -> tuple[int, int, str]:
    """Недорогой отпечаток файла: размер, время изменения (нс), sha1 первых 64 КБ.

    Полный хэш больших фотографий не нужен: заголовок JPEG/HEIC содержит EXIF
    с датой съемки и уникальными данными камеры.
    """
    st = os.stat(path)
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(HEAD_BYTES))
    return st.st_size, st.st_mtime_ns, h.hexdigest()


def scan_folder(folder: str | Path) -> list[PhotoItem]:
    """Список фотографий папки, отсортированный по EXIF-времени съемки."""
    items = []
    for p in find_images(folder):
        ts, from_exif = capture_time(p)
        try:
            size, mtime_ns, head = file_fingerprint(p)
        except OSError:
            size, mtime_ns, head = 0, 0, ""
        items.append(PhotoItem(source_path=str(p), capture_time=ts, capture_from_exif=from_exif,
                               file_size=size, file_mtime_ns=mtime_ns, file_head=head))
    items.sort(key=sort_key)
    return items


def path_key(path: str | Path) -> str:
    return Path(path).resolve().as_posix().casefold()


def same_file(old: PhotoItem, fresh: PhotoItem, saved_at: float | None = None) -> bool:
    """Тот же ли это файл, что был размечен раньше (а не другой файл с тем же именем)."""
    if old.has_fingerprint():
        if old.file_size != fresh.file_size or old.file_mtime_ns != fresh.file_mtime_ns:
            return False
        return not old.file_head or not fresh.file_head or old.file_head == fresh.file_head
    # Старый проект без отпечатка: сверяем дату съемки и то, что файл не менялся
    # после последнего сохранения проекта.
    if old.capture_time is not None and fresh.capture_time is not None:
        if abs(old.capture_time - fresh.capture_time) > LEGACY_TIME_TOL:
            return False
    if saved_at and fresh.file_mtime_ns and fresh.file_mtime_ns / 1e9 > saved_at + LEGACY_TIME_TOL:
        return False
    return True


def merge_rescan(saved: list[PhotoItem], folder: str | Path,
                 removed: list[str] | None = None, saved_at: float | None = None,
                 removed_fp: dict[str, list[int]] | None = None) -> list[PhotoItem]:
    """Объединяет сохраненную разметку с текущим содержимым папки.

    Разметка переносится, только если совпадает путь И отпечаток файла
    (размер, время изменения, начало файла). Другой файл с тем же именем —
    новая фотография без разметки. Новые файлы добавляются по дате,
    пропавшие помечаются как отсутствующие. Фото, убранные пользователем из
    партии (removed), не возвращаются — если это все еще тот же файл.
    """
    removed_keys = {path_key(p) for p in (removed or [])}
    removed_prints = {path_key(k): list(v) for k, v in (removed_fp or {}).items()}
    by_path = {path_key(p.source_path): p for p in saved}
    result: list[PhotoItem] = []
    seen = set()
    try:
        fresh = scan_folder(folder)
    except OSError:
        fresh = []
    replaced = 0
    for item in fresh:
        key = path_key(item.source_path)
        seen.add(key)
        old = by_path.get(key)
        if old is not None and same_file(old, item, saved_at):
            if key in removed_keys:
                continue
            if not old.has_fingerprint():          # миграция: дописать отпечаток
                old.file_size, old.file_mtime_ns, old.file_head = (
                    item.file_size, item.file_mtime_ns, item.file_head)
            old.missing = False
            result.append(old)
            continue
        if old is None and key in removed_keys:
            fp = removed_prints.get(key)
            if fp is None or fp == [item.file_size, item.file_mtime_ns]:
                continue                            # убран из партии — не возвращать
            # на месте убранного файла теперь другой файл — это новая фотография
        if old is not None:
            replaced += 1
        result.append(item)
    for key, old in by_path.items():
        if key not in seen and key not in removed_keys:
            old.missing = True
            result.append(old)
    if replaced:
        log.info("Заменено файлов с теми же именами (разметка не перенесена): %d", replaced)
    # Сохраняем прежний порядок известных файлов; новые — по времени.
    result.sort(key=sort_key)
    return result
