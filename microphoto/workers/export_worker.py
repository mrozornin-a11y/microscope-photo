"""Экспорт в отдельном потоке: прогресс, безопасная отмена, ошибки по файлам."""

from __future__ import annotations

import copy
import logging
import traceback
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from ..core.exporter import ExportPlan, file_signature, remove_empty_dirs, save_image
from ..core.models import PhotoItem, ProcessingSettings
from ..core.pipeline import ProcessingError, render

log = logging.getLogger(__name__)


@dataclass
class ExportSummary:
    done: int = 0
    errors: list[tuple[int, str, str]] = field(default_factory=list)   # (индекс, имя файла, сообщение)
    cancelled: bool = False
    removed_stale: int = 0


class ExportWorker(QThread):
    progress = Signal(int, int)                        # сделано, всего
    itemDone = Signal(int, str, str, object)           # индекс, статус, сообщение/путь, подпись файла
    finishedAll = Signal(object)                       # ExportSummary

    def __init__(self, photos: list[PhotoItem], plan: ExportPlan, settings: ProcessingSettings,
                 parent=None) -> None:
        super().__init__(parent)
        # снимок данных: GUI может продолжать работу, не мешая экспорту
        self.photos = {it.index: copy.deepcopy(photos[it.index]) for it in plan.items}
        self.plan = plan
        self.settings = settings.copy()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        summary = ExportSummary()
        total = len(self.plan.items)
        self.progress.emit(0, total)
        for n, item in enumerate(self.plan.items):
            if self._cancel:
                summary.cancelled = True
                break
            photo = self.photos[item.index]
            try:
                rendered = render(photo, self.settings)
                save_image(rendered.image, item.path, self.settings.export, rendered.source)
                sig = file_signature(item.path)
                summary.done += 1
                self.itemDone.emit(item.index, "done", str(item.path), sig)
            except ProcessingError as e:
                summary.errors.append((item.index, photo.file_name, str(e)))
                self.itemDone.emit(item.index, "error", str(e), None)
                log.warning("Ошибка обработки %s: %s", photo.source_path, e)
            except Exception as e:
                msg = _friendly(e)
                summary.errors.append((item.index, photo.file_name, msg))
                self.itemDone.emit(item.index, "error", msg, None)
                log.error("Ошибка обработки %s:\n%s", photo.source_path, traceback.format_exc())
            self.progress.emit(n + 1, total)
        if not summary.cancelled:
            emptied = set()
            for p in self.plan.stale_files:
                try:
                    p.unlink()
                    summary.removed_stale += 1
                    emptied.add(p.parent)
                except OSError:
                    pass
            if self.plan.out_dir is not None:
                remove_empty_dirs(emptied, self.plan.out_dir)
        self.finishedAll.emit(summary)


def _friendly(e: Exception) -> str:
    if isinstance(e, PermissionError):
        return "нет доступа к файлу (возможно, он открыт в другой программе)"
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "недостаточно места на диске"
    if isinstance(e, MemoryError):
        return "недостаточно памяти"
    text = str(e) or e.__class__.__name__
    if "truncated" in text or "cannot identify" in text:
        return "поврежденный файл"
    return text
