"""Проверка имен результатов перед обработкой: что не заполнено, где повторы."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import naming
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
    for same in by_path.values():
        if len(same) > 1:
            for i in same:
                others = ", ".join(f"№ {j + 1}" for j in same if j != i)
                rows[i].problems.append(f"имя совпадает с фото {others}")
    return rows
