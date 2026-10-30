"""Глобальные настройки программы (QSettings): окно, последние папки, настройки по умолчанию."""

from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QSettings

from .. import APP_NAME
from ..core.models import ProcessingSettings


class AppSettings:
    def __init__(self) -> None:
        self._s = QSettings(APP_NAME, APP_NAME)

    # окно
    def geometry(self) -> QByteArray | None:
        v = self._s.value("window/geometry")
        return v if isinstance(v, QByteArray) else None

    def set_geometry(self, g: QByteArray) -> None:
        self._s.setValue("window/geometry", g)

    # папки
    def last_folder(self) -> str:
        return str(self._s.value("paths/last_folder", "") or "")

    def set_last_folder(self, p: str) -> None:
        self._s.setValue("paths/last_folder", p)

    def last_output_folder(self) -> str:
        return str(self._s.value("paths/last_output", "") or "")

    def set_last_output_folder(self, p: str) -> None:
        self._s.setValue("paths/last_output", p)

    def last_list_folder(self) -> str:
        return str(self._s.value("paths/last_list", "") or "")

    def set_last_list_folder(self, p: str) -> None:
        self._s.setValue("paths/last_list", p)

    # настройки обработки по умолчанию (для новых партий)
    def processing(self) -> ProcessingSettings:
        raw = self._s.value("processing/json", "")
        try:
            return ProcessingSettings.from_dict(json.loads(raw)) if raw else ProcessingSettings()
        except Exception:
            return ProcessingSettings()

    def set_processing(self, s: ProcessingSettings) -> None:
        self._s.setValue("processing/json", json.dumps(s.to_dict(), ensure_ascii=False))

    # последние параметры съемки — подставляются в первую фотографию новой партии
    def last_light(self) -> str | None:
        return self._s.value("defaults/light") or None

    def last_mag(self) -> str | None:
        return self._s.value("defaults/mag") or None

    def remember_params(self, light: str | None, mag: str | None) -> None:
        if light:
            self._s.setValue("defaults/light", light)
        if mag:
            self._s.setValue("defaults/mag", mag)

    # число кнопок номера фотографии (1…N)
    def number_buttons(self) -> int:
        try:
            return max(20, min(200, int(self._s.value("ui/number_buttons", 20))))
        except (TypeError, ValueError):
            return 20

    def set_number_buttons(self, n: int) -> None:
        self._s.setValue("ui/number_buttons", int(n))

    # кэш миниатюр и preview (проекты — не кэш и автоматически не удаляются)
    def cache_auto(self) -> bool:
        return str(self._s.value("cache/auto", "true")).lower() in ("true", "1")

    def cache_max_gb(self) -> float:
        try:
            return max(0.2, float(self._s.value("cache/max_gb", 2.0)))
        except (TypeError, ValueError):
            return 2.0

    def cache_max_days(self) -> int:
        try:
            return max(1, int(self._s.value("cache/max_days", 30)))
        except (TypeError, ValueError):
            return 30

    def set_cache_policy(self, auto: bool, max_gb: float, max_days: int) -> None:
        self._s.setValue("cache/auto", "true" if auto else "false")
        self._s.setValue("cache/max_gb", float(max_gb))
        self._s.setValue("cache/max_days", int(max_days))

    def sync(self) -> None:
        self._s.sync()
