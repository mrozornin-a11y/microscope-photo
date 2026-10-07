"""Полный конвейер обработки одной фотографии — всегда из оригинала.

Порядок:
 1. поворот по EXIF;
 2. квадратная обрезка по подтвержденному кругу;
 3. черный фон вне круга;
 4. повышение резкости (до шкалы — текст и линия шкалы не «резкостятся»);
 5. масштабная шкала.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .cropper import apply_mask, crop_circle
from .image_loader import LoadedImage, load_oriented
from .models import PhotoItem, ProcessingSettings
from .project_ops import default_circle
from .scale_bar import draw_scale_bar
from .sharpness import sharpen


class ProcessingError(Exception):
    pass


@dataclass
class Rendered:
    image: Image.Image
    source: LoadedImage
    sharpened_only: Image.Image | None = None    # без шкалы (для сравнения в настройках)


def process_image(img: Image.Image, photo: PhotoItem, settings: ProcessingSettings,
                  with_scale: bool = True, max_side: int | None = None) -> Image.Image:
    circle = photo.circle or default_circle(img.width, img.height)
    out, mask = crop_circle(img, circle)
    if max_side and out.width > max_side:
        out = out.resize((max_side, max_side), Image.Resampling.LANCZOS)
        mask = mask.resize((max_side, max_side), Image.Resampling.BILINEAR)
    if settings.sharpen.enabled and settings.sharpen.amount > 0:
        out = apply_mask(sharpen(out, settings.sharpen), mask)
    if with_scale:
        out = add_scale(out, photo, settings)
    return out


def add_scale(img: Image.Image, photo: PhotoItem, settings: ProcessingSettings) -> Image.Image:
    if not settings.scale.enabled or photo.magnification is None:
        return img
    cal = settings.scale.calibration.get(photo.magnification)
    if cal is None:
        return img
    return draw_scale_bar(img, cal, settings.scale)


def render(photo: PhotoItem, settings: ProcessingSettings, max_side: int | None = None) -> Rendered:
    try:
        src = load_oriented(photo.source_path)
    except FileNotFoundError as e:
        raise ProcessingError("файл не найден") from e
    except Exception as e:
        raise ProcessingError(f"ошибка чтения: {e}") from e
    out = process_image(src.image, photo, settings, max_side=max_side)
    return Rendered(out, src)
