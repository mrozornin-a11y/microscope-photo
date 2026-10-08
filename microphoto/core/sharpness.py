"""Повышение резкости: Unsharp Mask по яркости.

Пользователь видит один параметр «Резкость» 0…100 (50 — рекомендуемое).
Функция usm_params() переводит его в технические параметры Unsharp Mask —
характер резкости можно подстраивать здесь, не трогая интерфейс.

Особенности реализации (цель — заметнее проявить мелкие детали: границы
зерен, трещины, микрорельеф — без «HDR-эффекта»):
  • резкость считается только по яркости и одинаково добавляется ко всем
    каналам — цветной шум и цветные каймы не усиливаются;
  • небольшой мягкий порог не дает поднимать шум в ровных участках;
  • величина добавки мягко ограничена (tanh), причем светлая сторона
    сильнее темной — так не появляются яркие ореолы вдоль контрастных границ;
  • радиус зависит от диаметра поля зрения (а не фиксирован в пикселях)
    и ограничен сверху, чтобы на снимках iPhone не получать «локальный контраст».

Это не воспроизведение алгоритма Microsoft Photos (он не опубликован),
а подобранный по ощущению аналог.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageEnhance

from .models import SharpenSettings

# Радиус (sigma размытия, px) = диаметр / RADIUS_DIVISOR, в пределах [MIN, MAX]
RADIUS_DIVISOR = 2000.0
RADIUS_MIN = 0.7
RADIUS_MAX = 1.8


@dataclass(frozen=True)
class UsmParams:
    sigma: float          # радиус размытия маски, px
    amount: float         # сила: 1.0 = +100 % к деталям
    threshold: float      # мягкий порог (уровни 0…255): мельче — считается шумом
    limit_light: float    # предел осветления пикселя
    limit_dark: float     # предел затемнения пикселя


def usm_params(user_value: int, diameter: int) -> UsmParams:
    """0…100 (интерфейс) → параметры Unsharp Mask для изображения с данным диаметром поля."""
    t = max(0.0, min(100.0, float(user_value))) / 100.0
    sigma = min(RADIUS_MAX, max(RADIUS_MIN, diameter / RADIUS_DIVISOR))
    return UsmParams(
        sigma=sigma,
        amount=3.2 * t ** 1.15,         # 25 → 0.65, 50 → 1.44, 75 → 2.31, 100 → 3.2
        threshold=1.0 + 0.6 * t,
        limit_light=16.0 + 34.0 * t,
        limit_dark=24.0 + 56.0 * t,
    )


def unsharp_mask(img: Image.Image, p: UsmParams) -> Image.Image:
    if p.amount <= 0:
        return img
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    y = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    blur = cv2.GaussianBlur(y, (0, 0), p.sigma, borderType=cv2.BORDER_REFLECT)
    detail = y - blur
    if p.threshold > 0:
        w = np.clip((np.abs(detail) - p.threshold) / p.threshold, 0.0, 1.0)
        detail *= w
    delta = detail * p.amount
    pos = delta > 0
    delta = np.where(pos, p.limit_light * np.tanh(delta / p.limit_light),
                     p.limit_dark * np.tanh(delta / p.limit_dark))
    out = rgb + delta[..., None]
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")


@dataclass(frozen=True)
class Sharpener:
    key: str
    title: str
    apply: Callable[[Image.Image, int, int], Image.Image]   # (изображение, сила 0…100, диаметр)


def _usm(img: Image.Image, amount: int, diameter: int) -> Image.Image:
    return unsharp_mask(img, usm_params(amount, diameter))


def _pillow_sharpness(img: Image.Image, amount: int, diameter: int) -> Image.Image:
    """Прежний алгоритм (слабый). Оставлен только для сравнения."""
    return ImageEnhance.Sharpness(img).enhance(1.0 + amount / 100.0)


SHARPENERS: dict[str, Sharpener] = {
    "usm": Sharpener("usm", "Нерезкая маска (Unsharp Mask)", _usm),
    "pillow": Sharpener("pillow", "Pillow Sharpness (прежний)", _pillow_sharpness),
}


def sharpen(img: Image.Image, settings: SharpenSettings, diameter: int | None = None) -> Image.Image:
    """diameter — диаметр поля зрения в пикселях этого изображения (по умолчанию ширина).

    Передается явно, когда резкость считается на фрагменте (preview 100 %).
    """
    if not settings.enabled or settings.amount <= 0:
        return img
    method = SHARPENERS.get(settings.method, SHARPENERS["usm"])
    return method.apply(img, settings.amount, diameter or img.width)
