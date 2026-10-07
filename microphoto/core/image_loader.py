"""Чтение изображений: поддержка форматов, поворот по EXIF, быстрые уменьшенные копии."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .constants import HEIC_EXTENSIONS, SUPPORTED_EXTENSIONS

log = logging.getLogger(__name__)

# Фотографии с телефона бывают очень большими — это не «бомба».
Image.MAX_IMAGE_PIXELS = 400_000_000

try:  # HEIC: поддержка через pillow-heif (готовые wheel-пакеты есть для Windows)
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except Exception:  # pragma: no cover - зависит от окружения
    HEIC_SUPPORTED = False

EXIF_ORIENTATION = 0x0112


def supported_extensions() -> set[str]:
    exts = set(SUPPORTED_EXTENSIONS)
    if HEIC_SUPPORTED:
        exts |= HEIC_EXTENSIONS
    return exts


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in supported_extensions()


@dataclass
class LoadedImage:
    image: Image.Image          # RGB, уже повернутое по EXIF
    icc_profile: bytes | None
    exif: Image.Exif | None


def _to_rgb(img: Image.Image) -> Image.Image:
    """Приводит изображение к 8-битному RGB, не искажая данные."""
    if img.mode == "RGB":
        return img
    if img.mode in ("I;16", "I;16B", "I;16L", "I;16N", "I"):
        arr = np.asarray(img, dtype=np.float64)
        maxv = 65535.0 if img.mode.startswith("I;16") or arr.max() > 255 else 255.0
        arr8 = np.clip(arr * (255.0 / maxv) + 0.5, 0, 255).astype(np.uint8)
        return Image.fromarray(arr8, "L").convert("RGB")
    if img.mode == "F":
        arr = np.asarray(img, dtype=np.float64)
        hi = arr.max() if arr.max() > 0 else 1.0
        return Image.fromarray(np.clip(arr / hi * 255, 0, 255).astype(np.uint8), "L").convert("RGB")
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (0, 0, 0))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


def _get_exif(img: Image.Image) -> Image.Exif | None:
    try:
        return img.getexif()
    except Exception:
        return None


def load_oriented(path: str | Path) -> LoadedImage:
    """Полное изображение в полном разрешении, повернутое по EXIF."""
    with Image.open(path) as src:
        icc = src.info.get("icc_profile")
        exif = _get_exif(src)
        src.load()
        img = ImageOps.exif_transpose(src)
        img = _to_rgb(img)
    return LoadedImage(img, icc, exif)


def oriented_size(path: str | Path) -> tuple[int, int]:
    """Размер изображения после поворота по EXIF (без полного декодирования)."""
    with Image.open(path) as src:
        w, h = src.size
        exif = _get_exif(src)
        orient = exif.get(EXIF_ORIENTATION, 1) if exif else 1
    if orient in (5, 6, 7, 8):
        return h, w
    return w, h


def load_preview(path: str | Path, max_side: int) -> tuple[Image.Image, tuple[int, int]]:
    """Уменьшенная копия (RGB, повернутая) и размер полного повернутого изображения.

    Для JPEG используется draft-режим — декодирование сразу в уменьшенном
    масштабе, это в разы быстрее.
    """
    with Image.open(path) as src:
        full_w, full_h = src.size
        exif = _get_exif(src)
        orient = exif.get(EXIF_ORIENTATION, 1) if exif else 1
        if src.format == "JPEG":
            k = max(full_w, full_h) / max_side
            if k >= 2:
                src.draft("RGB", (max(1, int(full_w / k)), max(1, int(full_h / k))))
        src.load()
        img = ImageOps.exif_transpose(src)
        img = _to_rgb(img)
    if orient in (5, 6, 7, 8):
        full = (full_h, full_w)
    else:
        full = (full_w, full_h)
    # Подстраховка: ориентация задана не только EXIF-тегом (например, в HEIC).
    if (img.width >= img.height) != (full[0] >= full[1]) and full[0] != full[1]:
        full = (full[1], full[0])
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return img, full
