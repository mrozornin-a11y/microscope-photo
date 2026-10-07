"""Квадратная обрезка по полю зрения и черный фон вне круга."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .models import Circle

_SHIFT = 4      # субпиксельная точность cv2.circle (1/16 пикселя)


def circle_mask(side: int, cx: float, cy: float, r: float) -> Image.Image:
    """Маска 'L': 255 внутри круга, 0 снаружи, сглаженный край."""
    m = np.zeros((side, side), np.uint8)
    k = 1 << _SHIFT
    cv2.circle(m, (int(round(cx * k)), int(round(cy * k))), int(round(r * k)), 255, -1,
               lineType=cv2.LINE_AA, shift=_SHIFT)
    return Image.fromarray(m, "L")


def crop_box(circle: Circle) -> tuple[int, int, int, int, int]:
    side = max(2, int(round(2 * circle.r)))
    x1 = int(round(circle.x - side / 2))
    y1 = int(round(circle.y - side / 2))
    return x1, y1, x1 + side, y1 + side, side


def crop_circle(img: Image.Image, circle: Circle) -> tuple[Image.Image, Image.Image]:
    """Квадрат 2R×2R с кругом поля зрения. Там, где нет данных исходника, — черное.

    Возвращает (изображение, маска круга).
    """
    x1, y1, x2, y2, side = crop_box(circle)
    # Image.crop сам дополняет нулями (черным) области за пределами кадра
    crop = img.crop((x1, y1, x2, y2))
    if crop.mode != "RGB":
        crop = crop.convert("RGB")
    mask = circle_mask(side, circle.x - x1, circle.y - y1, circle.r)
    return apply_mask(crop, mask), mask


def apply_mask(img: Image.Image, mask: Image.Image) -> Image.Image:
    black = Image.new("RGB", img.size, (0, 0, 0))
    return Image.composite(img, black, mask)
