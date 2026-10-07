"""Ресурсы программы (иконки)."""

import sys
from pathlib import Path


def resource_path(name: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    p = base / "microphoto" / "resources" / name
    if not p.exists():
        p = Path(__file__).resolve().parent / name
    return p.as_posix()
