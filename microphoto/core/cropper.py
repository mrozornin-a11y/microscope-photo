"""Квадратная обрезка по полю зрения и однотонный фон (черный или белый) вне круга."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .models import Circle

_SHIFT = 4      # субпиксельная точность cv2.circle (1/16 пикселя)

BACKGROUND_RGB = {"black": (0, 0, 0), "white": (255, 255, 255)}


def background_rgb(name: str) -> tuple[int, int, int]:
    return BACKGROUND_RGB.get(name, (0, 0, 0))


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


def crop_square(img: Image.Image, circle: Circle) -> tuple[Image.Image, Image.Image]:
    """Квадрат 2R×2R без маски (реальные пиксели снимка) и маска круга.

    Там, где кадр не покрывает квадрат, Image.crop дополняет нулями (черным).
    """
    x1, y1, x2, y2, side = crop_box(circle)
    crop = img.crop((x1, y1, x2, y2))
    if crop.mode != "RGB":
        crop = crop.convert("RGB")
    mask = circle_mask(side, circle.x - x1, circle.y - y1, circle.r)
    return crop, mask


def crop_circle(img: Image.Image, circle: Circle, background: str = "black") -> tuple[Image.Image, Image.Image]:
    """Квадрат 2R×2R с кругом поля зрения и заданным фоном вне круга.

    Возвращает (изображение, маска круга).
    """
    crop, mask = crop_square(img, circle)
    return apply_mask(crop, mask, background), mask


def apply_mask(img: Image.Image, mask: Image.Image, background: str = "black") -> Image.Image:
    bg = Image.new("RGB", img.size, background_rgb(background))
    return Image.composite(img, bg, mask)
