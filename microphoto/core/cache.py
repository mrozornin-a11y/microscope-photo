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
            _touch(meta_p)          # отметка «использовалось» — для очистки старого кэша
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


def _touch(p: Path) -> None:
    now = time.time()
    try:
        st = p.stat()
        if now - st.st_mtime > 3600:          # не чаще раза в час
            os.utime(p, (now, now))
    except OSError:
        pass


# ------------------------------------------------------------------ обслуживание
# Все функции ниже работают ТОЛЬКО внутри папки кэша. Файлы проектов
# (projects/*.json) и последней сессии лежат в другой папке и никогда не удаляются.

_CACHE_SUFFIXES = {".jpg", ".json", ".tmp"}


def _cache_files() -> list[Path]:
    root = cache_dir().resolve()
    out = []
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in _CACHE_SUFFIXES and root in p.resolve().parents:
                out.append(p)
        except OSError:
            pass
    return out


def _entries() -> list[tuple[float, int, list[Path]]]:
    """Записи кэша (preview + миниатюра + json одного файла): (последнее использование, размер, файлы)."""
    groups: dict[str, list[Path]] = {}
    for p in _cache_files():
        key = p.name.split("_")[0].split(".")[0]
        groups.setdefault(key, []).append(p)
    entries = []
    for files in groups.values():
        last, size = 0.0, 0
        for f in files:
            try:
                st = f.stat()
                last = max(last, st.st_mtime)
                size += st.st_size
            except OSError:
                pass
        entries.append((last, size, files))
    return entries


def cache_size() -> int:
    total = 0
    for p in _cache_files():
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def _remove(files: list[Path]) -> int:
    freed = 0
    for f in files:
        try:
            size = f.stat().st_size
            f.unlink()
            freed += size
        except OSError:
            pass
    return freed


def clear_cache() -> int:
    """Удалить все миниатюры и preview. Возвращает освобожденный объем (байт)."""
    freed = _remove(_cache_files())
    log.info("Кэш очищен: %.1f МБ", freed / 1e6)
    return freed


def prune(max_age_days: float = 30, max_bytes: int | None = 2 * 1024 ** 3) -> int:
    """Автоочистка: сначала записи старше max_age_days, затем — самые давние,
    пока кэш не станет меньше max_bytes. Возвращает освобожденный объем."""
    limit = time.time() - max_age_days * 86400
    entries = _entries()
    freed = 0
    keep = []
    for last, size, files in entries:
        if last < limit:
            freed += _remove(files)
        else:
            keep.append((last, size, files))
    if max_bytes is not None:
        total = sum(size for _, size, _ in keep)
        for last, size, files in sorted(keep, key=lambda e: e[0]):
            if total <= max_bytes:
                break
            freed += _remove(files)
            total -= size
    if freed:
        log.info("Кэш: автоочистка освободила %.1f МБ", freed / 1e6)
    return freed
