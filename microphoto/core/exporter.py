"""Экспорт: планирование имен, сохранение файлов.

Правила для имен:
  • файлы, которые программа сама создала для этой партии и которые с тех пор
    не менялись, при пересборке перезаписываются (или удаляются, если стали
    не нужны — например, сменился формат);
  • любые другие существующие файлы никогда не перезаписываются — новое имя
    получает суффикс «__повтор_2», «__повтор_3» …
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import naming
from .exif_utils import exif_for_output
from .image_loader import LoadedImage
from .models import ExportSettings, PhotoItem

log = logging.getLogger(__name__)


@dataclass
class ExportItem:
    index: int
    path: Path
    duplicate: bool = False          # имя получило суффикс «__повтор_N»


@dataclass
class ExportPlan:
    items: list[ExportItem] = field(default_factory=list)
    skipped_incomplete: list[int] = field(default_factory=list)
    stale_files: list[Path] = field(default_factory=list)    # старые результаты этой партии, ставшие ненужными

    @property
    def duplicates(self) -> int:
        return sum(1 for it in self.items if it.duplicate)


def file_signature(path: Path) -> list[float]:
    st = path.stat()
    return [float(st.st_size), float(st.st_mtime_ns)]


def is_own_file(photo: PhotoItem) -> bool:
    """Файл результата этой фотографии существует и не менялся с момента записи."""
    if not photo.output_path or not photo.output_signature:
        return False
    p = Path(photo.output_path)
    try:
        return p.is_file() and file_signature(p) == list(photo.output_signature)
    except OSError:
        return False


def _key(p: Path) -> str:
    return os.path.normcase(str(p.resolve()))


def plan_export(photos: list[PhotoItem], indices: list[int], out_dir: str | Path,
                settings: ExportSettings) -> ExportPlan:
    out_dir = Path(out_dir)
    plan = ExportPlan()
    own: dict[str, int] = {}
    for i, p in enumerate(photos):
        if is_own_file(p) and _key(Path(p.output_path).parent) == _key(out_dir):
            own[_key(Path(p.output_path))] = i
    used: set[str] = set()
    for i in indices:
        p = photos[i]
        name = naming.output_file_name(p, settings.format)
        if name is None:
            plan.skipped_incomplete.append(i)
            continue
        n = 1
        candidate = name
        while True:
            path = out_dir / candidate
            key = _key(path)
            if key not in used and (key in own or not path.exists()):
                break
            n += 1
            candidate = naming.duplicate_name(name, n)
        used.add(key)
        plan.items.append(ExportItem(i, path, duplicate=n > 1))
    planned = {_key(it.path) for it in plan.items}
    plan.stale_files = [Path(photos[i].output_path) for k, i in own.items() if k not in planned]
    return plan


def save_image(img: Image.Image, path: Path, settings: ExportSettings, source: LoadedImage | None = None) -> None:
    """Сохранение через временный файл: при сбое не остается «полуфайлов»."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.tmp{path.suffix}")
    params: dict = {}
    if source is not None and source.icc_profile:
        params["icc_profile"] = source.icc_profile
    exif = exif_for_output(source.exif) if source is not None else None
    if img.mode != "RGB":
        img = img.convert("RGB")
    fmt = settings.format
    try:
        if fmt == "jpg":
            if exif:
                params["exif"] = exif
            img.save(tmp, "JPEG", quality=settings.jpeg_quality, subsampling=0, **params)
        elif fmt == "tiff":
            # EXIF в TIFF через Pillow пишется некорректно — сохраняем только ICC-профиль
            img.save(tmp, "TIFF", compression="tiff_deflate", **params)
        else:
            if exif:
                params["exif"] = exif
            img.save(tmp, "PNG", **params)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
