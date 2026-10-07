"""Программное рисование масштабной шкалы.

Длина шкалы = доля диаметра поля зрения (калибровка). После квадратной
обрезки ширина изображения равна диаметру поля зрения, поэтому длина
считается от ширины итогового квадрата.

Вид:      0.5 mm
        |________|
Подпись по центру над линией, на концах линии — короткие засечки вверх.
Толщина линии, засечки, шрифт и отступ пропорциональны диаметру.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, ImageStat

from .models import CalibrationEntry, ScaleSettings

log = logging.getLogger(__name__)

# Доли диаметра поля зрения
FONT_SIZE = {"small": 0.022, "normal": 0.028, "large": 0.036}
THICKNESS = {"small": 0.0035, "normal": 0.0045, "large": 0.006}
MARGIN = {"small": 0.015, "normal": 0.03, "large": 0.05}
TICK_K = 2.6        # высота засечек — в толщинах линии
GAP_K = 0.9         # зазор между подписью и засечками — в толщинах линии
OUTLINE_K = 0.32    # толщина обводки — в толщинах линии

FONT_CANDIDATES = (
    "arial.ttf", "Arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf",
    "Helvetica.ttc", "FreeSans.ttf",
)

LIGHT = (255, 255, 255)
DARK = (0, 0, 0)


@functools.lru_cache(maxsize=32)
def get_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    size = max(6, int(size))
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # очень старый Pillow
        return ImageFont.load_default()


@dataclass
class BarGeometry:
    x1: int
    x2: int
    bar_top: int
    bar_bottom: int
    tick_top: int
    text_x: float
    text_baseline: float
    thickness: int
    outline: int
    font_size: int

    def bbox(self, text_h: int) -> tuple[int, int, int, int]:
        return self.x1, int(self.text_baseline - text_h), self.x2, self.bar_bottom


def geometry(width: int, height: int, fraction: float, s: ScaleSettings, label: str) -> BarGeometry:
    d = width                                   # ширина квадрата = диаметр поля зрения
    length = max(4, int(round(d * fraction)))
    th = max(2, int(round(d * THICKNESS.get(s.size, THICKNESS["normal"]))))
    margin = int(round(d * MARGIN.get(s.margin, MARGIN["normal"])))
    font_size = max(8, int(round(d * FONT_SIZE.get(s.size, FONT_SIZE["normal"]))))
    outline = max(1, int(round(th * OUTLINE_K)))
    tick = max(th + 2, int(round(th * TICK_K)))
    gap = max(2, int(round(th * GAP_K)))

    bar_bottom = height - margin
    bar_top = bar_bottom - th
    tick_top = bar_bottom - tick - th
    if s.position == "left":
        x1 = margin
    else:
        x1 = width - margin - length
    x2 = x1 + length
    text_x = (x1 + x2) / 2
    font = get_font(font_size)
    tw = font.getlength(label) if hasattr(font, "getlength") else font.getbbox(label)[2]
    # подпись не должна выходить за край кадра
    half = tw / 2 + outline + 1
    text_x = min(max(text_x, half + 1), width - half - 1)
    text_baseline = tick_top - gap
    return BarGeometry(x1, x2, bar_top, bar_bottom, tick_top, text_x, text_baseline, th, outline, font_size)


def _auto_style(img: Image.Image, g: BarGeometry) -> str:
    box = (max(0, g.x1), max(0, int(g.text_baseline - g.font_size * 1.1)),
           min(img.width, g.x2), min(img.height, g.bar_bottom))
    if box[2] <= box[0] or box[3] <= box[1]:
        return "white"
    region = img.crop(box).convert("L")
    mean = ImageStat.Stat(region).mean[0]
    return "black" if mean > 140 else "white"


def draw_scale_bar(img: Image.Image, cal: CalibrationEntry, s: ScaleSettings) -> Image.Image:
    """Рисует шкалу на копии изображения и возвращает ее."""
    out = img.copy() if img.mode == "RGB" else img.convert("RGB")
    g = geometry(out.width, out.height, cal.fraction, s, cal.label)
    style = s.style
    if style == "auto":
        style = _auto_style(out, g)
    fill, edge = (LIGHT, DARK) if style == "white" else (DARK, LIGHT)

    draw = ImageDraw.Draw(out)
    th = g.thickness
    rects = [
        (g.x1, g.bar_top, g.x2 - 1, g.bar_bottom - 1),              # линия
        (g.x1, g.tick_top, g.x1 + th - 1, g.bar_bottom - 1),        # левая засечка
        (g.x2 - th, g.tick_top, g.x2 - 1, g.bar_bottom - 1),        # правая засечка
    ]
    o = g.outline
    for x1, y1, x2, y2 in rects:          # сначала обводка (объединение фигур)
        draw.rectangle((x1 - o, y1 - o, x2 + o, y2 + o), fill=edge)
    for r in rects:
        draw.rectangle(r, fill=fill)
    font = get_font(g.font_size)
    try:
        draw.text((g.text_x, g.text_baseline), cal.label, font=font, fill=fill, anchor="ms",
                  stroke_width=o, stroke_fill=edge)
    except (TypeError, ValueError):     # растровый шрифт без поддержки anchor
        draw.text((g.text_x, g.text_baseline - g.font_size), cal.label, font=font, fill=fill)
    return out
