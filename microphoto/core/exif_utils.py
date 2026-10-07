"""Дата съемки из EXIF и подготовка EXIF для результата."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

TAG_DATETIME = 0x0132            # IFD0 DateTime (дата изменения в камере)
TAG_EXIF_IFD = 0x8769
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004
TAG_SUBSEC_ORIGINAL = 0x9291
TAG_SUBSEC_DIGITIZED = 0x9292
TAG_ORIENTATION = 0x0112


def _parse_exif_datetime(value, subsec=None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")
    text = str(value).strip().strip("\x00")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text[:19] if "S" in fmt else text[:16], fmt)
            break
        except ValueError:
            continue
    else:
        return None
    if dt.year < 1990:
        return None
    ts = dt.timestamp()
    if subsec is not None:
        digits = "".join(ch for ch in str(subsec) if ch.isdigit())
        if digits:
            ts += float("0." + digits)
    return ts


def exif_capture_time(path: str | Path) -> float | None:
    """Время съемки из EXIF: DateTimeOriginal → DateTimeDigitized → DateTime."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            try:
                sub = exif.get_ifd(TAG_EXIF_IFD)
            except Exception:
                sub = {}
            candidates = (
                (sub.get(TAG_DATETIME_ORIGINAL), sub.get(TAG_SUBSEC_ORIGINAL)),
                (sub.get(TAG_DATETIME_DIGITIZED), sub.get(TAG_SUBSEC_DIGITIZED)),
                (exif.get(TAG_DATETIME_ORIGINAL), None),
                (exif.get(TAG_DATETIME), None),
            )
            for value, subsec in candidates:
                ts = _parse_exif_datetime(value, subsec)
                if ts is not None:
                    return ts
    except Exception as e:  # поврежденный файл и т.п. — не повод падать
        log.debug("EXIF не прочитан %s: %s", path, e)
    return None


def file_time(path: str | Path) -> float:
    """Запасной вариант: самая ранняя из дат создания/изменения файла."""
    st = os.stat(path)
    times = [st.st_mtime]
    birth = getattr(st, "st_birthtime", None)
    if birth:
        times.append(birth)
    if os.name == "nt":
        times.append(st.st_ctime)   # на Windows ctime — дата создания
    return min(times)


def capture_time(path: str | Path) -> tuple[float, bool]:
    """(время, взято_ли_из_EXIF)."""
    ts = exif_capture_time(path)
    if ts is not None:
        return ts, True
    try:
        return file_time(path), False
    except OSError:
        return 0.0, False


def exif_for_output(exif: Image.Exif | None) -> bytes | None:
    """EXIF исходника для сохранения в результат (ориентация сброшена в 1)."""
    if not exif:
        return None
    try:
        exif = Image.Exif() if exif is None else exif
        exif[TAG_ORIENTATION] = 1
        # Миниатюра исходного кадра в результате не нужна и может не совпадать
        for tag in (0x0201, 0x0202):  # JPEGInterchangeFormat / Length
            if tag in exif:
                del exif[tag]
        return exif.tobytes()
    except Exception as e:
        log.debug("EXIF для результата не сформирован: %s", e)
        return None
