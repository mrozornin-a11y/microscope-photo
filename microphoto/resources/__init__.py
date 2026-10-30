"""Ресурсы программы (иконки)."""

from pathlib import Path


def resource_path(name: str) -> str:
    return (Path(__file__).resolve().parent / name).as_posix()
