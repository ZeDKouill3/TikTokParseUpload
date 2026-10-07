"""Bibliotheque clipper/montage.py : planche d'images legendee (SPEC-b0f3 R8)."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from clipper import montage as montage_lib
from clipper.montage import LABEL_HEIGHT, MontageError, montage


def write_image(path, width, height, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = color
    cv2.imwrite(str(path), img)


def batch_of(video_dir, specs):
    """specs : [(nom, largeur, hauteur, couleur, timecode)]."""
    batch = []
    for name, w, h, color, timecode in specs:
        write_image(video_dir / "frames" / name, w, h, color)
        batch.append({"path": f"frames/{name}", "timecode": timecode})
    return batch


def test_label_height_is_28():
    assert LABEL_HEIGHT == 28


def test_montage_is_a_horizontal_grid_named_after_the_index(tmp_path):
    video_dir = tmp_path / "video"
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    batch = batch_of(video_dir, [("a.jpg", 200, 100, (0, 0, 200), 1.0), ("b.jpg", 200, 100, (0, 200, 0), 2.0), ("c.jpg", 200, 100, (200, 0, 0), 3.0)])
    dest = montage(batch, video_dir, dest_dir, 768, 7)
    assert dest == dest_dir / "00007_montage.jpg"
    img = cv2.imread(str(dest))
    h, w = img.shape[:2]
    assert (w, h) == (600, 100 + LABEL_HEIGHT)
    # chaque cellule garde sa couleur, dans l'ordre du lot (tolerance JPEG)
    for i, expected in enumerate([(0, 0, 200), (0, 200, 0), (200, 0, 0)]):
        pixel = img[LABEL_HEIGHT + 50, i * 200 + 100]
        assert np.abs(pixel.astype(int) - np.array(expected)).max() < 20


def test_each_cell_has_a_label_band_with_text(tmp_path):
    video_dir = tmp_path / "video"
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    batch = batch_of(video_dir, [("a.jpg", 300, 100, (0, 0, 0), 12.5), ("b.jpg", 300, 100, (0, 0, 0), 40.0)])
    img = cv2.imread(str(montage(batch, video_dir, dest_dir, 768, 0)))
    for i in range(2):
        band = img[0:LABEL_HEIGHT, i * 300 : (i + 1) * 300]
        assert band.max() > 100  # du texte blanc sur fond noir


def test_label_text_is_image_index_and_timecode(tmp_path, monkeypatch):
    video_dir = tmp_path / "video"
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    batch = batch_of(video_dir, [("a.jpg", 300, 100, (0, 0, 0), 12.54), ("b.jpg", 300, 100, (0, 0, 0), 40.0)])
    texts = []
    real = cv2.putText

    def spy(img, text, *args, **kwargs):
        texts.append(text)
        return real(img, text, *args, **kwargs)

    monkeypatch.setattr(montage_lib.cv2, "putText", spy)
    montage(batch, video_dir, dest_dir, 768, 0)
    assert texts == ["Image 0 : 12.5 s", "Image 1 : 40.0 s"]


def test_wide_images_are_reduced_to_max_width_keeping_ratio(tmp_path):
    video_dir = tmp_path / "video"
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    batch = batch_of(video_dir, [("a.jpg", 800, 400, (10, 10, 10), 1.0)])
    h, w = cv2.imread(str(montage(batch, video_dir, dest_dir, 200, 1))).shape[:2]
    assert (w, h) == (200, 100 + LABEL_HEIGHT)


def test_small_images_are_never_enlarged(tmp_path):
    video_dir = tmp_path / "video"
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    batch = batch_of(video_dir, [("a.jpg", 120, 60, (10, 10, 10), 1.0)])
    h, w = cv2.imread(str(montage(batch, video_dir, dest_dir, 768, 1))).shape[:2]
    assert (w, h) == (120, 60 + LABEL_HEIGHT)


def test_original_images_are_left_intact(tmp_path):
    video_dir = tmp_path / "video"
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    batch = batch_of(video_dir, [("a.jpg", 800, 400, (10, 10, 10), 1.0)])
    original = (video_dir / "frames" / "a.jpg").read_bytes()
    montage(batch, video_dir, dest_dir, 200, 1)
    assert (video_dir / "frames" / "a.jpg").read_bytes() == original


def test_unreadable_image_error_names_the_file(tmp_path):
    video_dir = tmp_path / "video"
    dest_dir = tmp_path / "out"
    dest_dir.mkdir()
    batch = batch_of(video_dir, [("a.jpg", 100, 50, (0, 0, 0), 1.0)])
    batch.append({"path": "frames/absente.jpg", "timecode": 2.0})
    with pytest.raises(MontageError, match="absente.jpg"):
        montage(batch, video_dir, dest_dir, 768, 0)


def test_unwritable_destination_error_names_the_file(tmp_path):
    video_dir = tmp_path / "video"
    batch = batch_of(video_dir, [("a.jpg", 100, 50, (0, 0, 0), 1.0)])
    missing_dir = tmp_path / "n_existe_pas"
    with pytest.raises(MontageError, match="00003_montage.jpg"):
        montage(batch, video_dir, missing_dir, 768, 3)


def test_library_imports_no_pipeline_step():
    import ast

    tree = ast.parse(open(montage_lib.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not {m for m in imported if m.startswith("clipper")}
