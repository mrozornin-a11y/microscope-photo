"""Старые проекты и временные данные: разметка не должна переходить к другим файлам."""

import json
import os
import time
from datetime import datetime

import pytest

from microphoto.core import cache, state
from microphoto.core.models import Circle, PhotoItem, Project
from microphoto.core.paths import cache_dir, projects_dir
from microphoto.core.scanner import merge_rescan, scan_folder
from synth import make_field, save_photo


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctrl(qapp):
    from microphoto.gui.app_settings import AppSettings
    from microphoto.gui.controller import ProjectController

    c = ProjectController(AppSettings())
    yield c
    c._save_timer.stop()


def _photos(folder, n=3, seed=0):
    for i in range(n):
        arr = make_field(240, 240, 120, 120, 100, seed=seed + i)
        save_photo(folder / f"IMG_000{i + 1}.JPG", arr, datetime(2025, 1, 1, 10, i))


def _mark(c, i, name="A", mag="10"):
    c.edit(i, {"sample_name": name, "light_mode": "refl", "magnification": mag, "photo_number": i + 1,
               "circle": Circle(120, 120, 100), "circle_confirmed": True}, "test")


def test_replaced_file_does_not_inherit_markup(ctrl, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    _photos(folder, 1)
    ctrl.open_folder(str(folder))
    _mark(ctrl, 0, "A", "10")
    ctrl.save_now()

    # заменить IMG_0001.JPG другим снимком с тем же именем
    time.sleep(0.02)
    save_photo(folder / "IMG_0001.JPG", make_field(300, 260, 150, 130, 110, seed=99), datetime(2025, 6, 1, 9, 0))

    saved = state.load_project_for(str(folder))
    assert saved is not None
    ctrl.open_folder(str(folder), saved)
    p = ctrl.photos[0]
    assert p.sample_name == "" and p.magnification is None and p.light_mode is None
    assert p.photo_number is None and p.circle is None and not p.circle_confirmed


def test_unchanged_file_keeps_markup(ctrl, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    _photos(folder, 2)
    ctrl.open_folder(str(folder))
    _mark(ctrl, 1, "B", "20")
    ctrl.save_now()
    ctrl.open_folder(str(folder), state.load_project_for(str(folder)))
    assert ctrl.photos[1].sample_name == "B" and ctrl.photos[1].magnification == "20"


def test_start_new_project_clears_everything(ctrl, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    _photos(folder, 3)
    ctrl.open_folder(str(folder))
    for i in range(3):
        _mark(ctrl, i, "Св-1")
    ctrl.set_name_list(["Св-1", "Св-2"])
    ctrl.remove_photos([2])
    ctrl.save_now()
    assert state.project_file(str(folder)).exists()
    assert state.last_session_folder() == str(folder)

    ctrl.start_new_project()

    # открылось как совершенно новая партия
    assert len(ctrl.photos) == 3                      # убранное фото тоже вернулось как новое
    assert all(p.params_empty() and p.circle is None and not p.circle_confirmed for p in ctrl.photos)
    assert ctrl.project.name_list == [] and ctrl.project.removed_paths == []
    assert ctrl.undo_stack.count() == 0
    # исходные файлы на месте
    assert sorted(os.listdir(folder)) == ["IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG"]

    # повторное открытие той же папки — без старой разметки и старого списка названий
    ctrl.save_now()
    ctrl.open_folder(str(folder), state.load_project_for(str(folder)))
    assert all(p.params_empty() and p.circle is None for p in ctrl.photos)
    assert ctrl.project.name_list == []


def test_start_new_removes_only_that_project_json(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    for f in (a, b):
        state.save_project(Project(source_dir=str(f), photos=[PhotoItem(str(f / "x.jpg"), sample_name="S")]))
    state.start_new(str(a))
    assert not state.project_file(str(a)).exists()
    assert state.project_file(str(b)).exists()
    assert state.last_session_folder() == str(b)      # последняя сессия относится к другой папке


def test_same_size_and_mtime_but_different_content(tmp_path):
    p = tmp_path / "IMG_1.JPG"
    p.write_bytes(b"A" * 5000)
    os.utime(p, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    old = scan_folder(tmp_path)[0]
    old.sample_name = "A"
    p.write_bytes(b"B" * 5000)
    os.utime(p, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    merged = merge_rescan([old], tmp_path)
    assert merged[0].sample_name == ""


def test_legacy_project_without_fingerprint(tmp_path):
    """Старый JSON без отпечатков: неизмененный файл сохраняет разметку (и получает
    отпечаток), замененный после сохранения проекта — нет."""
    _photos(tmp_path, 2)
    items = scan_folder(tmp_path)
    data = Project(source_dir=str(tmp_path), photos=items).to_dict()
    for d in data["photos"]:
        d.pop("file_size"), d.pop("file_mtime_ns"), d.pop("file_head")
        d["sample_name"] = "OLD"
    data.pop("saved_at")
    pf = state.project_file(str(tmp_path))
    pf.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    old_time = time.time() - 100
    os.utime(pf, (old_time, old_time))
    for f in tmp_path.glob("*.JPG"):
        os.utime(f, (old_time - 50, old_time - 50))
    # второй файл заменен уже после сохранения проекта
    save_photo(tmp_path / "IMG_0002.JPG", make_field(240, 240, 120, 120, 100, seed=7), datetime(2025, 1, 1, 10, 1))

    saved = state.load_project_for(str(tmp_path))
    merged = merge_rescan(saved.photos, tmp_path, saved.removed_paths, saved.saved_at)
    by_name = {p.file_name: p for p in merged}
    assert by_name["IMG_0001.JPG"].sample_name == "OLD" and by_name["IMG_0001.JPG"].has_fingerprint()
    assert by_name["IMG_0002.JPG"].sample_name == ""


def test_removed_photo_replaced_by_new_file_appears(tmp_path):
    _photos(tmp_path, 2)
    items = scan_folder(tmp_path)
    gone = items[1]
    fp = {gone.source_path: [gone.file_size, gone.file_mtime_ns]}
    assert [p.file_name for p in merge_rescan([items[0]], tmp_path, [gone.source_path], None, fp)] == \
        ["IMG_0001.JPG"]
    time.sleep(0.02)
    save_photo(tmp_path / "IMG_0002.JPG", make_field(300, 300, 150, 150, 120, seed=5), datetime(2025, 2, 1))
    names = [p.file_name for p in merge_rescan([items[0]], tmp_path, [gone.source_path], None, fp)]
    assert names == ["IMG_0001.JPG", "IMG_0002.JPG"]


# ------------------------------------------------------------------ кэш
def _fake_entry(key: str, size: int, age_days: float) -> None:
    d = cache_dir() / key[:2]
    d.mkdir(parents=True, exist_ok=True)
    t = time.time() - age_days * 86400
    for name in (f"{key}_p.jpg", f"{key}_t.jpg", f"{key}.json"):
        f = d / name
        f.write_bytes(b"x" * size)
        os.utime(f, (t, t))


def test_cache_prune_by_age_and_size_never_touches_projects():
    cache.clear_cache()
    proj = projects_dir() / "keep_me.json"
    proj.write_text("{}", "utf-8")
    os.utime(proj, (0, 0))                                   # очень старый файл проекта
    _fake_entry("aa" + "0" * 38, 1000, 60)                   # старше срока
    _fake_entry("bb" + "0" * 38, 1000, 10)                   # самый давний из свежих
    _fake_entry("cc" + "0" * 38, 1000, 5)
    _fake_entry("dd" + "0" * 38, 1000, 1)
    assert cache.cache_size() == 12000
    cache.prune(max_age_days=30, max_bytes=7000)
    left = sorted({p.name[:2] for p in cache_dir().rglob("*") if p.is_file()})
    assert left == ["cc", "dd"]                              # старое и самое давнее удалены
    assert cache.cache_size() <= 7000
    assert proj.exists()
    cache.clear_cache()
    assert cache.cache_size() == 0 and proj.exists()


def test_preview_recreated_after_cache_clear(tmp_path):
    _photos(tmp_path, 1)
    p = next(tmp_path.glob("*.JPG"))
    m = cache.get_or_create(p)
    assert m.preview_path.exists()
    cache.clear_cache()
    assert not m.preview_path.exists()
    m2 = cache.get_or_create(p)
    assert m2.preview_path.exists() and m2.full_size == m.full_size
