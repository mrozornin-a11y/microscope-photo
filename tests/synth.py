"""Синтетические «микрофотографии» для тестов: круглое поле зрения на темном фоне."""

from __future__ import annotations

from datetime import datetime, timedelta

import cv2
import numpy as np
from PIL import Image


def make_field(w: int, h: int, cx: float, cy: float, r: float, seed: int = 0,
               mode: str = "normal", glare: bool = False, blur_edge: float = 6.0) -> np.ndarray:
    """RGB uint8. mode: normal / crossed (много черного внутри) / dark_half / bright."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # «зерна» — диаграмма Вороного с разными цветами
    n = 160
    pts = rng.uniform([0, 0], [w, h], size=(n, 2)).astype(np.float32)
    small_w, small_h = max(1, w // 8), max(1, h // 8)
    sy, sx = np.mgrid[0:small_h, 0:small_w].astype(np.float32)
    d = (sx[..., None] * 8 - pts[:, 0]) ** 2 + (sy[..., None] * 8 - pts[:, 1]) ** 2
    lab = d.argmin(axis=2)
    if mode == "crossed":
        colors = rng.uniform(0, 1, size=(n, 3))
        dark = rng.uniform(0, 1, n) < 0.55
        colors[dark] *= 0.04
        colors[~dark] = colors[~dark] * 200 + 30
    elif mode == "bright":
        colors = rng.uniform(170, 240, size=(n, 3))
    else:
        base = rng.uniform(70, 200, size=(n, 1))
        colors = np.clip(base + rng.normal(0, 15, size=(n, 3)), 20, 250)
    img_small = colors[lab].astype(np.float32)
    img = cv2.resize(img_small, (w, h), interpolation=cv2.INTER_NEAREST)
    # трещины / детали
    for _ in range(40):
        p1 = tuple(int(v) for v in rng.uniform([0, 0], [w, h]))
        p2 = (p1[0] + int(rng.normal(0, w / 8)), p1[1] + int(rng.normal(0, h / 8)))
        cv2.line(img, p1, p2, (20, 20, 20), max(1, w // 800))
    if mode == "dark_half":
        # темная пустая часть поля (как на примере пользователя)
        mask = (xx - cx) * 0.8 + (yy - cy) * 0.6 < -r * 0.15
        img[mask] = 50
    # виньетирование поля
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    vign = 1 - 0.35 * np.clip(rr / r, 0, 1) ** 3
    img *= vign[..., None]
    # мягкий край поля
    edge = np.clip((r - rr) / blur_edge + 0.5, 0, 1)
    img *= edge[..., None]
    if glare:
        g = np.exp(-(((xx - w * 0.85) ** 2 + (yy - h * 0.1) ** 2) / (2 * (w * 0.08) ** 2))) * 60
        img += g[..., None]
    img += rng.normal(0, 3, size=img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def save_photo(path, arr: np.ndarray, when: datetime | None = None, orientation: int = 1,
               quality: int = 90) -> None:
    """Сохранить как JPEG с EXIF. orientation != 1: пиксели хранятся «повернутыми»,
    как это делает камера телефона, а тег указывает, как их развернуть."""
    img = Image.fromarray(arr)
    if orientation == 6:      # нужно повернуть на 90° по часовой для показа
        img = img.transpose(Image.Transpose.ROTATE_90)
    elif orientation == 8:
        img = img.transpose(Image.Transpose.ROTATE_270)
    elif orientation == 3:
        img = img.transpose(Image.Transpose.ROTATE_180)
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = "Apple"
    exif[0x0110] = "iPhone 15"
    if when is not None:
        ifd = exif.get_ifd(0x8769)
        ifd[0x9003] = when.strftime("%Y:%m:%d %H:%M:%S")
    img.save(path, "JPEG", quality=quality, exif=exif.tobytes())


def make_series(folder, count: int = 8, w: int = 1512, h: int = 2016, start: datetime | None = None):
    """Серия фото с небольшими сдвигами поля зрения. Возвращает список (имя, cx, cy, r) в
    координатах показа."""
    from pathlib import Path

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    start = start or datetime(2025, 3, 14, 10, 0, 0)
    out = []
    rng = np.random.default_rng(42)
    modes = ["normal", "dark_half", "crossed", "normal", "bright", "normal", "crossed", "dark_half"]
    for k in range(count):
        cx = w * 0.5 + rng.normal(0, w * 0.01)
        cy = h * 0.55 + rng.normal(0, h * 0.01)
        r = w * 0.42 * (1 + rng.normal(0, 0.005))
        arr = make_field(w, h, cx, cy, r, seed=k, mode=modes[k % len(modes)])
        # имена в «перепутанном» порядке, а даты — правильные
        name = f"IMG_{9000 - k * 7}.JPG"
        save_photo(folder / name, arr, start + timedelta(seconds=37 * k), orientation=6 if k % 3 == 0 else 1)
        out.append((name, cx, cy, r))
    return out
