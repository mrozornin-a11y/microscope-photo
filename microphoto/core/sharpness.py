"""Повышение резкости.

Алгоритм вынесен сюда, чтобы его можно было заменить (например, на Unsharp
Mask), не трогая интерфейс: GUI знает только «включено» и «сила, %».
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageEnhance, ImageFilter

from .models import SharpenSettings


@dataclass(frozen=True)
class Sharpener:
    key: str
    title: str
    apply: Callable[[Image.Image, int], Image.Image]     # (изображение, сила 0…100 %)


def _pillow_sharpness(img: Image.Image, amount: int) -> Image.Image:
    # 1.0 = 0 %, 1.5 = +50 %, 2.0 = +100 %
    return ImageEnhance.Sharpness(img).enhance(1.0 + amount / 100.0)


def _unsharp_mask(img: Image.Image, amount: int) -> Image.Image:
    radius = max(1.0, min(img.size) / 1500.0)
    return img.filter(ImageFilter.UnsharpMask(radius=radius, percent=int(amount * 1.6), threshold=2))


SHARPENERS: dict[str, Sharpener] = {
    "pillow": Sharpener("pillow", "Стандартная (Pillow Sharpness)", _pillow_sharpness),
    "unsharp": Sharpener("unsharp", "Нерезкая маска (Unsharp Mask)", _unsharp_mask),
}


def sharpen(img: Image.Image, settings: SharpenSettings) -> Image.Image:
    if not settings.enabled or settings.amount <= 0:
        return img
    method = SHARPENERS.get(settings.method, SHARPENERS["pillow"])
    return method.apply(img, settings.amount)
