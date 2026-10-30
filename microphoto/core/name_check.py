"""Проверка имен результатов перед обработкой: что не заполнено, где повторы."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import naming
from .constants import MAG_BY_KEY
from .models import PhotoItem


@dataclass
class NameRow:
    index: int                      # позиция в списке (0…)
    source_name: str
    new_name: str                   # имя файла результата или ""
    folder: str                     # папка шлифа или ""
    problems: list[str] = field(default_factory=list)
    excluded: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems


def missing_params(p: PhotoItem) -> list[str]:
    out = []
    if not p.sample_name.strip():
        out.append("название")
    if p.light_mode is None:
        out.append("освещение")
    if p.magnification is None:
        out.append("увеличение")
    if p.photo_number is None:
        out.append("номер")
    return out


def check_names(photos: list[PhotoItem], fmt: str, unreadable: set[int] | None = None) -> list[NameRow]:
    """Строка таблицы на каждую фотографию; problems пуст — все в порядке."""
    unreadable = unreadable or set()
    rows: list[NameRow] = []
    by_path: dict[str, list[int]] = {}
    for i, p in enumerate(photos):
        rel = naming.output_relpath(p, fmt)
        row = NameRow(i, p.file_name, rel.name if rel else "", rel.parent.name if rel else "",
                      excluded=p.excluded)
        rows.append(row)
        if p.excluded:
            continue
        if p.missing:
            row.problems.append("файл не найден")
        elif i in unreadable:
            row.problems.append("файл не открывается")
        miss = missing_params(p)
        if miss:
            row.problems.append("не задано: " + ", ".join(miss))
        if rel is not None:
            by_path.setdefault(rel.as_posix().casefold(), []).append(i)
    _check_one_magnification_per_number(photos, rows)
    for same in by_path.values():
        if len(same) > 1:
            for i in same:
                others = ", ".join(f"№ {j + 1}" for j in same if j != i)
                rows[i].problems.append(f"имя совпадает с фото {others}")
    return rows


def _check_one_magnification_per_number(photos: list[PhotoItem], rows: list[NameRow]) -> None:
    """У одного номера фото (в пределах шлифа) увеличение всегда одно.

    Например, у трех снимков № 6 шлифа Св-25-14 может быть разное освещение,
    но увеличение у всех трех должно совпадать.
    """
    groups: dict[tuple[str, int], list[int]] = {}
    for i, p in enumerate(photos):
        if p.excluded or p.photo_number is None or p.magnification is None or not p.sample_name.strip():
            continue
        key = (naming.sanitize(p.sample_name).casefold(), p.photo_number)
        groups.setdefault(key, []).append(i)
    for (_sample, number), idx in groups.items():
        by_mag: dict[str, list[int]] = {}
        for i in idx:
            by_mag.setdefault(photos[i].magnification, []).append(i)
        if len(by_mag) < 2:
            continue
        parts = []
        for mag, ii in sorted(by_mag.items(), key=lambda kv: float(kv[0])):
            title = MAG_BY_KEY[mag].title
            parts.append(f"{title} — фото " + ", ".join(f"№ {i + 1}" for i in ii))
        text = f"у номера {number} разные увеличения: " + "; ".join(parts)
        for i in idx:
            rows[i].problems.append(text)
