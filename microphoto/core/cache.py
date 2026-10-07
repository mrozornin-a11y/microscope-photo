"""Дисковый кэш уменьшенных копий (preview) и миниатюр.

Ключ кэша — путь, размер и время изменения файла, поэтому измененный
оригинал автоматически получает новую копию. Оригиналы не копируются.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .image_loader import load_preview
from .paths import cache_dir

log = logging.getLogger(__name__)

PREVIEW_SIDE = 2048
THUMB_SIDE = 160
CACHE_VERSION = 2


@dataclass
class CachedMedia:
    preview_path: Path
    thumb_path: Path
    full_size: tuple[int, int]      # размер оригинала после поворота


def _key(path: Path) -> str:
    st = path.stat()
    raw = f"{CACHE_VERSION}|{path.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def _tmp(p: Path) -> Path:
    return p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")


def cached_paths(path: str | Path) -> tuple[Path, Path, Path]:
    path = Path(path)
    k = _key(path)
    d = cache_dir() / k[:2]
    return d / f"{k}_p.jpg", d / f"{k}_t.jpg", d / f"{k}.json"


def get_or_create(path: str | Path) -> CachedMedia:
    """Возвращает (при необходимости создает) preview и миниатюру."""
    path = Path(path)
    preview_p, thumb_p, meta_p = cached_paths(path)
    if preview_p.exists() and thumb_p.exists() and meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text("utf-8"))
            return CachedMedia(preview_p, thumb_p, (int(meta["w"]), int(meta["h"])))
        except Exception:
            pass
    img, full = load_preview(path, PREVIEW_SIDE)
    preview_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(preview_p)
    img.save(tmp, "JPEG", quality=92)
    os.replace(tmp, preview_p)
    thumb = img.copy()
    thumb.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    tmp = _tmp(thumb_p)
    thumb.save(tmp, "JPEG", quality=85)
    os.replace(tmp, thumb_p)
    tmp = _tmp(meta_p)
    tmp.write_text(json.dumps({"w": full[0], "h": full[1], "src": str(path)}), "utf-8")
    os.replace(tmp, meta_p)
    return CachedMedia(preview_p, thumb_p, full)


def prune(max_age_days: int = 45) -> None:
    """Удаляет давно не использовавшиеся файлы кэша."""
    limit = time.time() - max_age_days * 86400
    root = cache_dir()
    removed = 0
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.stat().st_atime < limit and p.stat().st_mtime < limit:
                p.unlink()
                removed += 1
        except OSError:
            pass
    if removed:
        log.info("Кэш: удалено старых файлов: %d", removed)
