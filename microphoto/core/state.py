"""Автосохранение работы в JSON.

Для каждой исходной папки — свой файл состояния (только пути, метаданные,
координаты и настройки; изображения не сохраняются). Отдельный файл
last_session.json указывает на последнюю работу.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from .models import Project
from .paths import data_dir, projects_dir

log = logging.getLogger(__name__)


def _folder_key(folder: str) -> str:
    norm = os.path.normcase(os.path.abspath(folder))
    return hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:16]


def project_file(folder: str) -> Path:
    return projects_dir() / f"{_folder_key(folder)}.json"


def _last_session_file() -> Path:
    return data_dir() / "last_session.json"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, path)


def save_project(project: Project) -> None:
    if not project.source_dir:
        return
    data = json.dumps(project.to_dict(), ensure_ascii=False, indent=1)
    _atomic_write(project_file(project.source_dir), data)
    _atomic_write(_last_session_file(), json.dumps({"source_dir": project.source_dir}, ensure_ascii=False))


def load_project_for(folder: str) -> Project | None:
    path = project_file(folder)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        project = Project.from_dict(data)
        if not project.photos:
            return None
        return project
    except Exception:
        log.exception("Не удалось прочитать состояние %s", path)
        return None


def last_session_folder() -> str | None:
    path = _last_session_file()
    if not path.exists():
        return None
    try:
        folder = json.loads(path.read_text("utf-8")).get("source_dir")
        return folder or None
    except Exception:
        return None


def clear_last_session() -> None:
    try:
        _last_session_file().unlink()
    except OSError:
        pass


def forget_project(folder: str) -> None:
    try:
        project_file(folder).unlink()
    except OSError:
        pass


def project_has_work(project: Project) -> bool:
    """Есть ли что продолжать: хоть что-то размечено и работа не завершена экспортом."""
    if project.finished:
        return False
    return any(not p.params_empty() or p.circle_confirmed for p in project.photos)
