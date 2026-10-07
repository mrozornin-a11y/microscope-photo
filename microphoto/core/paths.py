"""Служебные папки программы: состояние, кэш, логи."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import APP_NAME


def data_dir() -> Path:
    override = os.environ.get("MICROPHOTO_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    return _sub("cache")


def logs_dir() -> Path:
    return _sub("logs")


def projects_dir() -> Path:
    return _sub("projects")
