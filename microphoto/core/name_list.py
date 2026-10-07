"""Загрузка списка названий шлифов из TXT / CSV / XLSX."""

from __future__ import annotations

import csv
import io
from pathlib import Path


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _unique(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        s = str(v).strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def load_names(path: str | Path) -> list[str]:
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.worksheets[0]
            values = [row[0] if row else None for row in ws.iter_rows(min_col=1, max_col=1, values_only=True)]
        finally:
            wb.close()
        return _unique(values)

    text = _decode(path.read_bytes())
    if ext == ".csv":
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        except csv.Error:
            class dialect(csv.excel):  # noqa: N801
                delimiter = ";" if sample.count(";") > sample.count(",") else ","
        rows = csv.reader(io.StringIO(text), dialect)
        return _unique(row[0] if row else None for row in rows)
    return _unique(text.splitlines())
