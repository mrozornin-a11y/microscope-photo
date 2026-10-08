import math
from datetime import datetime

import numpy as np
import pytest
from PIL import Image

from microphoto.core import exporter, naming, project_ops, state
from microphoto.core.circle_detector import detect_circle
from microphoto.core.cropper import crop_circle
from microphoto.core.models import Circle, ExportSettings, PhotoItem, ProcessingSettings, Project
from microphoto.core.name_list import load_names
from microphoto.core.pipeline import render
from microphoto.core.scale_bar import geometry
from microphoto.core.scanner import scan_folder
from synth import make_field, save_photo


def photo(**kw):
    base = dict(source_path="x.jpg", sample_name="Св-25-14", light_mode="refl", magnification="10", photo_number=1)
    base.update(kw)
    return PhotoItem(**base)


# ------------------------------------------------------------------ имена
def test_output_name_format():
    assert naming.output_file_name(photo(), "jpg") == "1_Св-25-14_отраж_10х.jpg"
    assert naming.output_file_name(photo(light_mode="ppl", magnification="2.5", photo_number=3), "tiff") == \
        "3_Св-25-14_пп_2,5х.tif"
    assert naming.output_file_name(photo(light_mode="xpl", magnification="20"), "png") == "1_Св-25-14_сп_20х.png"


def test_output_name_sanitized_and_incomplete():
    assert naming.output_stem(photo(sample_name='a\\b/c:d*e?f"g<h>i|j')) == "1_abcdefghij_отраж_10х"
    assert naming.output_stem(photo(sample_name="")) is None
    assert naming.output_stem(photo(magnification=None)) is None
    assert naming.duplicate_name("1_a.jpg", 2) == "1_a__повтор_2.jpg"


# ------------------------------------------------------------------ наследование
def test_inherit_fills_only_blanks_and_increments_number():
    ps = [photo(photo_number=7), PhotoItem("b.jpg"), PhotoItem("c.jpg", sample_name="Другой")]
    assert project_ops.inherit_values(ps, 1) == {
        "sample_name": "Св-25-14", "light_mode": "refl", "magnification": "10", "photo_number": 8}
    v = project_ops.inherit_values(ps, 2)
    assert "sample_name" not in v and v["photo_number"] == 8


def test_inherit_skips_excluded():
    ps = [photo(photo_number=1), PhotoItem("b.jpg", excluded=True), PhotoItem("c.jpg")]
    assert project_ops.inherit_values(ps, 2)["photo_number"] == 2


def test_apply_params_forward_renumbers():
    ps = [photo(photo_number=4)] + [PhotoItem(f"{i}.jpg") for i in range(5)]
    ch = project_ops.apply_params_forward(ps, 0, 3, True, True, False, True)
    assert [i for i, _ in ch] == [1, 2, 3]
    assert [c["photo_number"] for _, c in ch] == [5, 6, 7]
    assert all("magnification" not in c for _, c in ch)
    ch_all = project_ops.apply_params_forward(ps, 0, None, True, True, True, True)
    assert len(ch_all) == 5


def test_apply_circle_forward():
    ps = [photo(circle=Circle(10, 20, 30), width=100, height=100)] + \
        [PhotoItem(f"{i}.jpg", width=100, height=100) for i in range(4)]
    ch = project_ops.apply_circle_forward(ps, 0, 2)
    assert [i for i, _ in ch] == [1, 2]
    assert all(c["circle"] == Circle(10, 20, 30) and c["circle_confirmed"] for _, c in ch)


# ------------------------------------------------------------------ обрезка
def test_crop_square_and_black_outside():
    img = Image.new("RGB", (400, 300), (200, 100, 50))
    out, mask = crop_circle(img, Circle(200, 150, 100))
    assert out.size == (200, 200)
    assert out.getpixel((2, 2)) == (0, 0, 0)               # угол — черный
    assert out.getpixel((100, 100)) == (200, 100, 50)     # центр — данные


def test_crop_outside_frame_is_padded_black():
    img = Image.new("RGB", (300, 300), (255, 255, 255))
    out, _ = crop_circle(img, Circle(20, 150, 100))       # круг выходит за левый край
    assert out.size == (200, 200)
    assert out.getpixel((30, 100)) == (0, 0, 0)            # за пределами кадра
    assert out.getpixel((150, 100)) == (255, 255, 255)


# ------------------------------------------------------------------ шкала
def test_scale_length_from_diameter():
    s = ProcessingSettings().scale
    g = geometry(2000, 2000, 0.229, s, "0.5 mm")
    assert g.x2 - g.x1 == 458                              # 2000 × 0.229
    assert g.x2 < 2000 and g.bar_bottom < 2000
    s.position = "left"
    g2 = geometry(2000, 2000, 0.229, s, "0.5 mm")
    assert g2.x1 < 1000


def test_render_pipeline_size_and_scale(tmp_path):
    arr = make_field(900, 1200, 450, 650, 380, seed=1)
    p = tmp_path / "a.jpg"
    save_photo(p, arr, datetime(2025, 1, 1), orientation=6)
    item = photo(source_path=str(p), circle=Circle(450, 650, 380))
    r = render(item, ProcessingSettings())
    assert r.image.size == (760, 760)
    px = np.asarray(r.image)
    assert px[5, 5].max() == 0
    # шкала белая в правом нижнем углу
    assert (px[650:740, 480:740] > 240).all(axis=2).sum() > 50


# ------------------------------------------------------------------ детектор
@pytest.mark.parametrize("mode", ["normal", "dark_half", "crossed", "bright"])
def test_detector_accuracy(mode):
    w, h, cx, cy, r = 1200, 1600, 610, 870, 500
    arr = make_field(w, h, cx, cy, r, seed=5, mode=mode)
    d = detect_circle(arr)
    c = d.circle
    assert math.hypot(c.x - cx, c.y - cy) < 0.01 * r
    assert abs(c.r - r) < 0.01 * r


def test_detector_never_crashes_on_flat_image():
    d = detect_circle(np.zeros((300, 400, 3), np.uint8))
    assert not d.confident and d.circle.r > 0


def test_detector_uses_prior():
    arr = make_field(1600, 1200, 800, 600, 640, seed=98, mode="crossed")
    d = detect_circle(arr, prior=Circle(810, 590, 630))
    assert math.hypot(d.circle.x - 800, d.circle.y - 600) < 8 and abs(d.circle.r - 640) < 8


# ------------------------------------------------------------------ папка, EXIF
def test_scan_sorts_by_exif_time(tmp_path):
    arr = make_field(200, 200, 100, 100, 80)
    save_photo(tmp_path / "IMG_0003.JPG", arr, datetime(2025, 1, 1, 10, 0, 0))
    save_photo(tmp_path / "IMG_0001.JPG", arr, datetime(2025, 1, 1, 10, 5, 0))
    save_photo(tmp_path / "IMG_0002.JPG", arr, datetime(2025, 1, 1, 10, 2, 0))
    (tmp_path / "notes.txt").write_text("x")
    names = [p.file_name for p in scan_folder(tmp_path)]
    assert names == ["IMG_0003.JPG", "IMG_0002.JPG", "IMG_0001.JPG"]


# ------------------------------------------------------------------ экспорт
def test_plan_export_duplicates_and_ownership(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    ps = [photo(source_path="a.jpg"), photo(source_path="b.jpg"), photo(source_path="c.jpg", photo_number=2)]
    plan = exporter.plan_export(ps, [0, 1, 2], out, ExportSettings())
    names = [it.path.name for it in plan.items]
    assert names == ["1_Св-25-14_отраж_10х.jpg", "1_Св-25-14_отраж_10х__повтор_2.jpg", "2_Св-25-14_отраж_10х.jpg"]

    # чужой файл не перезаписывается, свой — перезаписывается
    (out / "2_Св-25-14_отраж_10х.jpg").write_bytes(b"foreign")
    own = out / "1_Св-25-14_отраж_10х.jpg"
    own.write_bytes(b"ours")
    ps[0].output_path = str(own)
    ps[0].output_signature = exporter.file_signature(own)
    plan = exporter.plan_export(ps, [0, 2], out, ExportSettings())
    assert [it.path.name for it in plan.items] == ["1_Св-25-14_отраж_10х.jpg", "2_Св-25-14_отраж_10х__повтор_2.jpg"]

    # смена формата: старый собственный JPG становится устаревшим
    plan = exporter.plan_export(ps, [0], out, ExportSettings(format="tiff"))
    assert plan.stale_files == [own]


def test_save_formats(tmp_path):
    img = Image.new("RGB", (50, 50), (10, 20, 30))
    for fmt, ext in (("jpg", ".jpg"), ("tiff", ".tif"), ("png", ".png")):
        p = tmp_path / f"r{ext}"
        exporter.save_image(img, p, ExportSettings(format=fmt))
        with Image.open(p) as im:
            assert im.size == (50, 50)
            if fmt == "tiff":
                assert im.info.get("compression") == "tiff_adobe_deflate"
    assert not list(tmp_path.glob(".*tmp*"))


# ------------------------------------------------------------------ состояние, списки
def test_project_roundtrip(tmp_path):
    pr = Project(source_dir=str(tmp_path), photos=[photo(circle=Circle(1.5, 2.5, 3.5), circle_confirmed=True)])
    pr.settings.sharpen.amount = 70
    pr.settings.scale.calibration["10"].fraction = 0.3
    state.save_project(pr)
    back = state.load_project_for(str(tmp_path))
    assert back is not None
    assert back.photos[0].circle == Circle(1.5, 2.5, 3.5) and back.photos[0].circle_confirmed
    assert back.settings.sharpen.amount == 70
    assert back.settings.scale.calibration["10"].fraction == 0.3
    assert state.last_session_folder() == str(tmp_path)


def test_load_names(tmp_path):
    (tmp_path / "a.txt").write_text("Св-1\n\nСв-2\nсв-1\n", "utf-8")
    assert load_names(tmp_path / "a.txt") == ["Св-1", "Св-2"]
    (tmp_path / "b.csv").write_text("Название;Комментарий\nШ-5;x\nШ-6;y\n", "cp1251")
    assert load_names(tmp_path / "b.csv") == ["Название", "Ш-5", "Ш-6"]
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for v in ["A-1", None, "A-2", "A-1", 15]:
        ws.append([v])
    wb.save(tmp_path / "c.xlsx")
    assert load_names(tmp_path / "c.xlsx") == ["A-1", "A-2", "15"]


# ------------------------------------------------------------------ фон, цвет шкалы, резкость
def test_white_background_is_pure_white():
    img = Image.new("RGB", (400, 400), (90, 120, 60))
    out, _ = crop_circle(img, Circle(200, 200, 150), "white")
    assert out.getpixel((1, 1)) == (255, 255, 255)
    assert out.getpixel((150, 150)) == (90, 120, 60)


def test_scale_color_auto_follows_background():
    from microphoto.core.scale_bar import scale_color

    s = ProcessingSettings().scale
    assert s.color_mode == "auto"
    assert scale_color(s, "black") == "white"
    assert scale_color(s, "white") == "black"
    s.color_mode = "white"                        # выбран вручную — фон не влияет
    assert scale_color(s, "white") == "white"


def test_old_settings_migrate():
    s = ProcessingSettings.from_dict({"scale": {"style": "white"}, "sharpen": {"method": "pillow"}})
    assert s.scale.color_mode == "auto" and s.sharpen.method == "usm" and s.background_color == "black"
    s2 = ProcessingSettings.from_dict(ProcessingSettings(background_color="white").to_dict())
    assert s2.background_color == "white"


def test_usm_params_monotonic_and_radius_limited():
    from microphoto.core.sharpness import usm_params

    amounts = [usm_params(v, 2600).amount for v in (0, 25, 50, 75, 100)]
    assert amounts[0] == 0 and amounts == sorted(amounts)
    assert usm_params(50, 12000).sigma <= 2.0      # огромный кадр — радиус ограничен
    assert usm_params(50, 300).sigma >= 0.7


def test_sharpen_stronger_than_old_pillow():
    from PIL import ImageEnhance

    from microphoto.core.models import SharpenSettings
    from microphoto.core.sharpness import sharpen

    rng = np.random.default_rng(1)
    base = np.full((300, 300), 120, np.float32)
    base[:, 150:] = 160
    base += rng.normal(0, 6, base.shape)
    import cv2

    img = Image.fromarray(np.clip(cv2.GaussianBlur(base, (0, 0), 1.5), 0, 255).astype(np.uint8)).convert("RGB")

    def edge(im):
        # профиль, усредненный по строкам (шум усредняется) — крутизна границы
        prof = np.asarray(im.convert("L"), np.float32)[:, 140:160].mean(axis=0)
        return float(np.abs(np.diff(prof)).max())

    orig = edge(img)
    old = edge(ImageEnhance.Sharpness(img).enhance(1.5))
    new50 = edge(sharpen(img, SharpenSettings(True, 50), diameter=2600))
    new100 = edge(sharpen(img, SharpenSettings(True, 100), diameter=2600))
    assert old - orig < 0.5                 # прежний алгоритм границу почти не менял
    assert new50 > orig + 0.8 and new100 > new50 + 1.5


def test_scale_bar_not_sharpened(tmp_path):
    """Шкала рисуется после резкости: ее пиксели одинаковы при любой резкости."""
    arr = make_field(900, 900, 450, 450, 420, seed=2)
    p = tmp_path / "a.jpg"
    save_photo(p, arr, datetime(2025, 1, 1))
    item = photo(source_path=str(p), circle=Circle(450, 450, 420))
    s0, s1 = ProcessingSettings(), ProcessingSettings()
    s0.sharpen.enabled = False
    s1.sharpen.amount = 100
    a0 = np.asarray(render(item, s0).image)
    a1 = np.asarray(render(item, s1).image)
    white0 = (a0 == 255).all(axis=2)
    assert white0[700:, 500:].sum() > 100                      # шкала есть
    assert (a1[white0] == 255).all()                           # и не изменилась
    assert not np.array_equal(a0[300:500, 300:500], a1[300:500, 300:500])   # а снимок — резче


def test_removed_photos_do_not_come_back(tmp_path):
    from microphoto.core.scanner import merge_rescan

    arr = make_field(200, 200, 100, 100, 80)
    for i in range(3):
        save_photo(tmp_path / f"IMG_{i}.JPG", arr, datetime(2025, 1, 1, 10, i))
    items = scan_folder(tmp_path)
    removed = [items[1].source_path]
    saved = [items[0], items[2]]
    names = [p.file_name for p in merge_rescan(saved, tmp_path, removed)]
    assert names == ["IMG_0.JPG", "IMG_2.JPG"]
    pr = Project(source_dir=str(tmp_path), photos=saved, removed_paths=removed)
    assert Project.from_dict(pr.to_dict()).removed_paths == removed
