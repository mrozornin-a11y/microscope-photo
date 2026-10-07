"""Операции над партией фотографий: наследование параметров, применение к серии, статусы.

Функции ничего не меняют сами — они возвращают список изменений
[(индекс, {поле: новое значение})], который контроллер применяет через Undo.
"""

from __future__ import annotations

from typing import Any

from .models import Circle, PhotoItem

Changes = list[tuple[int, dict[str, Any]]]


def previous_active(photos: list[PhotoItem], index: int) -> int | None:
    for j in range(index - 1, -1, -1):
        if not photos[j].excluded:
            return j
    return None


def following_active(photos: list[PhotoItem], index: int, count: int | None) -> list[int]:
    out = []
    for j in range(index + 1, len(photos)):
        if photos[j].excluded:
            continue
        out.append(j)
        if count is not None and len(out) >= count:
            break
    return out


def _last_number_before(photos: list[PhotoItem], index: int) -> int | None:
    for j in range(index - 1, -1, -1):
        p = photos[j]
        if not p.excluded and p.photo_number is not None:
            return p.photo_number
    return None


def inherit_values(photos: list[PhotoItem], index: int) -> dict[str, Any]:
    """Что фотография получает от предыдущей: заполняются только пустые поля."""
    target = photos[index]
    if target.excluded:
        return {}
    prev_i = previous_active(photos, index)
    if prev_i is None:
        return {}
    prev = photos[prev_i]
    new: dict[str, Any] = {}
    if not target.sample_name.strip() and prev.sample_name.strip():
        new["sample_name"] = prev.sample_name
    if target.light_mode is None and prev.light_mode is not None:
        new["light_mode"] = prev.light_mode
    if target.magnification is None and prev.magnification is not None:
        new["magnification"] = prev.magnification
    if target.photo_number is None:
        last = _last_number_before(photos, index)
        if last is not None:
            new["photo_number"] = last + 1
    return new


def apply_params_forward(
    photos: list[PhotoItem],
    index: int,
    count: int | None,
    copy_name: bool,
    copy_light: bool,
    copy_mag: bool,
    renumber: bool,
) -> Changes:
    src = photos[index]
    changes: Changes = []
    number = src.photo_number
    for j in following_active(photos, index, count):
        new: dict[str, Any] = {}
        if copy_name:
            new["sample_name"] = src.sample_name
        if copy_light:
            new["light_mode"] = src.light_mode
        if copy_mag:
            new["magnification"] = src.magnification
        if renumber and number is not None:
            number += 1
            new["photo_number"] = number
        new = {k: v for k, v in new.items() if getattr(photos[j], k) != v}
        if new:
            changes.append((j, new))
    return changes


def circle_for_size(circle: Circle, src: PhotoItem, dst: PhotoItem) -> Circle:
    """Перенос круга между кадрами (если размеры кадров различаются — пропорционально)."""
    if src.width and dst.width and src.height and dst.height and (src.width, src.height) != (dst.width, dst.height):
        kx = dst.width / src.width
        ky = dst.height / src.height
        return Circle(circle.x * kx, circle.y * ky, circle.r * min(kx, ky))
    return circle


def apply_circle_forward(photos: list[PhotoItem], index: int, count: int | None) -> Changes:
    src = photos[index]
    if src.circle is None:
        return []
    changes: Changes = []
    for j in following_active(photos, index, count):
        dst = photos[j]
        c = circle_for_size(src.circle, src, dst)
        changes.append((j, {"circle": c, "circle_source": "series", "circle_confirmed": True}))
    return changes


def default_circle(width: int, height: int) -> Circle:
    """Приблизительный круг по центру — если автоопределение не уверено."""
    w = width or 1000
    h = height or 1000
    return Circle(w / 2, h / 2, min(w, h) * 0.45)


# ----------------------------------------------------------------- статусы

STATUS_EMPTY = "empty"
STATUS_PARAMS = "params"
STATUS_CIRCLE = "circle"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_EXCLUDED = "excluded"
STATUS_MISSING = "missing"

STATUS_TEXT = {
    STATUS_EMPTY: ("○", "не заполнено"),
    STATUS_PARAMS: ("✓", "параметры заданы"),
    STATUS_CIRCLE: ("✓", "круг проверен"),
    STATUS_DONE: ("✓", "готово"),
    STATUS_ERROR: ("⚠", "ошибка"),
    STATUS_EXCLUDED: ("—", "не обрабатывать"),
    STATUS_MISSING: ("⚠", "файл не найден"),
}


def photo_status(p: PhotoItem) -> str:
    if p.missing:
        return STATUS_MISSING
    if p.excluded:
        return STATUS_EXCLUDED
    if p.export_status == "error":
        return STATUS_ERROR
    if p.export_status == "done":
        return STATUS_DONE
    if not p.params_complete():
        return STATUS_EMPTY
    if p.circle_confirmed and p.circle is not None:
        return STATUS_CIRCLE
    return STATUS_PARAMS


def first_incomplete(photos: list[PhotoItem]) -> int | None:
    for i, p in enumerate(photos):
        if not p.excluded and not p.missing and not p.params_complete():
            return i
    return None


def first_unconfirmed(photos: list[PhotoItem], start: int = 0) -> int | None:
    n = len(photos)
    for k in range(n):
        i = (start + k) % n
        p = photos[i]
        if not p.excluded and not p.missing and not p.circle_confirmed:
            return i
    return None
