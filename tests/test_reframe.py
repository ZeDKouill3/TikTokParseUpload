from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from clipper import llm
from clipper.config import Config
from clipper.gpu import Device
from clipper.llm.fake import FakeBackend

VIDEO_ID = "abcdefghijk"
W, H = 1920, 1080
# Largeur d'un cadre 9:16 pleine hauteur dans une source 1920x1080.
CROP_W = 608


# --------------------------------------------------------------------------
# Fixtures : video, detecteur et reponses LLM factices. Les visages sont des
# boites englobantes synthetiques, fonction du temps (secondes, absolues).
# --------------------------------------------------------------------------


class FakeVideo:
    """Frame source factice : des images noires aux temps demandes. Garde le
    temps courant pour que le detecteur factice sache quoi renvoyer."""

    def __init__(self, width=W, height=H):
        self.width = width
        self.height = height
        self.current_t = None
        self.requested: list[float] = []

    def __call__(self, video_path, times):
        assert Path(video_path).exists()
        for t in times:
            self.requested.append(t)
            self.current_t = t
            yield t, np.zeros((self.height, self.width, 3), dtype=np.uint8)


class FakeDetector:
    def __init__(self, video, boxes_fn):
        self.video = video
        self.boxes_fn = boxes_fn
        self.closed = False

    def detect(self, frame):
        assert not self.closed, "detecteur utilise apres close()"
        assert frame.shape[:2] == (self.video.height, self.video.width)
        return [(*box, 0.9) for box in self.boxes_fn(self.video.current_t)]

    def close(self):
        self.closed = True


class FakeDetectorFactory:
    def __init__(self, video, boxes_fn):
        self.video = video
        self.boxes_fn = boxes_fn
        self.built: list[tuple[dict, Device]] = []
        self.detectors: list[FakeDetector] = []

    def __call__(self, settings, device):
        self.built.append((settings, device))
        detector = FakeDetector(self.video, self.boxes_fn)
        self.detectors.append(detector)
        return detector


def static(*boxes):
    return lambda t: list(boxes)


def make_config(tmp_path, **reframe):
    return Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={"reframe": reframe} if reframe else {},
    )


@pytest.fixture
def video_dir(tmp_path):
    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / f"{VIDEO_ID}.mp4").write_bytes(b"not really a video")
    write_scenes(d, [(0.0, 100.0)])
    return d


def write_scenes(video_dir, scenes):
    (video_dir / "scenes.json").write_text(
        json.dumps({"scenes": [{"start": s, "end": e} for s, e in scenes], "frames": []}),
        encoding="utf-8",
    )


def single(face):
    return {"layout": "single", "camera": None, "face": face, "reason": "r"}


def facecam(x, y, w, h):
    return {"layout": "facecam_gameplay", "camera": {"x": x, "y": y, "w": w, "h": h}, "face": None, "reason": "r"}


def run(tmp_path, boxes_fn, responses, *, start=10.0, end=14.0, clip_id="01", video=None, force=False, **reframe):
    from clipper.reframe import reframe as do_reframe

    video = video or FakeVideo()
    factory = FakeDetectorFactory(video, boxes_fn)
    fake = FakeBackend(responses)
    with llm.use_backend(fake):
        out = do_reframe(
            VIDEO_ID,
            clip_id,
            start,
            end,
            tmp_path / "workspace",
            config=make_config(tmp_path, **reframe),
            force=force,
            detector_factory=factory,
            frame_source=video,
        )
    return out, factory, fake


def load(out):
    return json.loads(Path(out).read_text(encoding="utf-8"))


def rects(plan, panel="main"):
    [p] = [p for p in plan["panels"] if p["name"] == panel]
    return p["rects"]


def contains(rect, box, eps=1e-6):
    x0, y0, x1, y1 = box
    return (
        rect["x"] <= x0 + eps
        and rect["y"] <= y0 + eps
        and x1 - eps <= rect["x"] + rect["w"]
        and y1 - eps <= rect["y"] + rect["h"]
    )


def cuts(rect, box):
    """Le cadre coupe le visage : il le touche sans le contenir entierement."""
    x0, y0, x1, y1 = box
    rx0, ry0, rx1, ry1 = rect["x"], rect["y"], rect["x"] + rect["w"], rect["y"] + rect["h"]
    intersects = x0 < rx1 and rx0 < x1 and y0 < ry1 and ry0 < y1
    return intersects and not contains(rect, box)


def times_in(rect, n=5):
    """Instants a verifier sur l'intervalle d'un rectangle, bornes comprises."""
    return [rect["start"] + (rect["end"] - rect["start"]) * k / (n - 1) for k in range(n)]


def assert_covers(rect_list, start, end):
    assert rect_list[0]["start"] == pytest.approx(start)
    assert rect_list[-1]["end"] == pytest.approx(end)
    for a, b in zip(rect_list, rect_list[1:]):
        assert a["end"] == pytest.approx(b["start"])


# --------------------------------------------------------------------------
# Sortie et plans
# --------------------------------------------------------------------------


def test_writes_workspace_reframe_clip_json(tmp_path, video_dir):
    out, _, _ = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)], clip_id="03-p2")

    assert Path(out) == video_dir / "reframe" / "03-p2.json"
    data = load(out)
    assert data["video_id"] == VIDEO_ID
    assert data["clip_id"] == "03-p2"
    assert (data["start"], data["end"]) == (10.0, 14.0)
    assert data["source"] == {"width": W, "height": H}
    assert data["output"] == {"width": 1080, "height": 1920}
    assert data["layout"] == "single"


def test_one_llm_call_per_plan_of_the_clip_with_an_annotated_image(tmp_path, video_dir):
    write_scenes(video_dir, [(0.0, 12.0), (12.0, 13.0), (13.0, 30.0)])
    out, _, fake = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)] * 3, start=10.0, end=14.0)

    data = load(out)
    assert [(p["start"], p["end"]) for p in data["plans"]] == [(10.0, 12.0), (12.0, 13.0), (13.0, 14.0)]
    assert len(fake.calls) == 3
    for call, plan in zip(fake.calls, data["plans"]):
        assert call.usage == "layout"
        [image] = call.images
        assert image.suffix == ".jpg" and image.exists()
        assert image.read_bytes()[:2] == b"\xff\xd8"  # JPEG
        assert (video_dir / plan["image"]) == image
        assert "#0" in call.prompt  # identifiant du visage annote sur l'image
    # Les rectangles couvrent le clip sans trou, plan apres plan.
    all_rects = [r for p in data["plans"] for r in rects(p)]
    assert_covers(all_rects, 10.0, 14.0)


def test_annotated_image_draws_the_detected_faces(tmp_path, video_dir):
    import cv2

    out, _, fake = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)])
    image = cv2.imread(str(fake.calls[0].images[0]))
    assert image is not None
    # Une image noire en entree : seuls les traces d'annotation sont non nuls.
    assert image.sum() > 0


def test_existing_result_is_not_recomputed_without_force(tmp_path, video_dir):
    out, _, _ = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)])
    out2, factory, fake = run(tmp_path, static((1100, 300, 1300, 500)), [])
    assert out2 == out
    assert factory.built == [] and fake.calls == []

    out3, factory, fake = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)], force=True)
    assert len(fake.calls) == 1


def test_missing_scenes_json_is_an_error(tmp_path, video_dir):
    from clipper.reframe import ReframeError

    (video_dir / "scenes.json").unlink()
    with pytest.raises(ReframeError):
        run(tmp_path, static(), [single(None)])


# --------------------------------------------------------------------------
# Detecteur, device et liberation du modele (ADR-fb9b)
# --------------------------------------------------------------------------


def test_detector_gets_device_from_clipper_gpu_and_is_closed_before_llm(tmp_path, video_dir, monkeypatch):
    import clipper.reframe as reframe_mod

    monkeypatch.setattr(reframe_mod, "get_device", lambda: Device(type="cuda", compute_type="float16"))
    seen = {}

    def answer(request):
        seen["closed"] = [d.closed for d in factory_ref[0].detectors]
        return single(0)

    factory_ref = []
    video = FakeVideo()
    from clipper.reframe import reframe as do_reframe

    factory = FakeDetectorFactory(video, static((1100, 300, 1300, 500)))
    factory_ref.append(factory)
    with llm.use_backend(FakeBackend([answer])):
        do_reframe(VIDEO_ID, "01", 10.0, 14.0, tmp_path / "workspace",
                   config=make_config(tmp_path), detector_factory=factory, frame_source=video)

    [(settings, device)] = factory.built
    assert device.type == "cuda"
    assert settings["detector"] == "mediapipe"
    assert seen["closed"] == [True]


def test_detector_is_closed_even_when_detection_fails(tmp_path, video_dir):
    def boom(t):
        raise RuntimeError("detection en echec")

    from clipper.reframe import reframe as do_reframe

    video = FakeVideo()
    factory = FakeDetectorFactory(video, boom)
    with llm.use_backend(FakeBackend([])), pytest.raises(RuntimeError, match="detection en echec"):
        do_reframe(VIDEO_ID, "01", 10.0, 14.0, tmp_path / "workspace",
                   config=make_config(tmp_path), detector_factory=factory, frame_source=video)
    assert [d.closed for d in factory.detectors] == [True]


def test_unknown_detector_in_config_is_an_error(tmp_path, video_dir):
    from clipper.reframe import ReframeError, reframe as do_reframe

    with llm.use_backend(FakeBackend([])), pytest.raises(ReframeError, match="yolo"):
        do_reframe(VIDEO_ID, "01", 10.0, 14.0, tmp_path / "workspace",
                   config=make_config(tmp_path, detector="yolo"), frame_source=FakeVideo())


def test_reframe_is_configurable_through_config_toml(tmp_path):
    from clipper.config import load_config

    (tmp_path / "config.toml").write_text('[reframe]\nsample_fps = 3.0\nfallback = "blur"\n', encoding="utf-8")
    section = load_config(tmp_path / "config.toml").section("reframe")
    assert section["sample_fps"] == 3.0
    assert section["fallback"] == "blur"
    assert section["detector"] == "mediapipe"


# --------------------------------------------------------------------------
# Reponse LLM : validee avant usage (ADR-b1c1)
# --------------------------------------------------------------------------


def test_facecam_without_camera_is_a_schema_error_and_nothing_is_written(tmp_path, video_dir):
    bad = {"layout": "facecam_gameplay", "camera": None, "face": None, "reason": "r"}
    with pytest.raises(llm.SchemaError):
        run(tmp_path, static((1100, 300, 1300, 500)), [bad])
    assert not (video_dir / "reframe" / "01.json").exists()


def test_single_with_unknown_face_is_a_schema_error(tmp_path, video_dir):
    with pytest.raises(llm.SchemaError):
        run(tmp_path, static((1100, 300, 1300, 500)), [single(7)])


def test_unknown_layout_is_a_schema_error(tmp_path, video_dir):
    with pytest.raises(llm.SchemaError):
        run(tmp_path, static((1100, 300, 1300, 500)), [{"layout": "split", "camera": None, "face": None, "reason": "r"}])


def test_camera_outside_the_image_is_a_schema_error(tmp_path, video_dir):
    with pytest.raises(llm.SchemaError):
        run(tmp_path, static((1500, 800, 1600, 900)), [facecam(0.8, 0.7, 0.5, 0.3)])


def test_llm_failure_propagates_and_nothing_is_written(tmp_path, video_dir):
    with pytest.raises(llm.TransientLLMError):
        run(tmp_path, static((1100, 300, 1300, 500)), [llm.TransientLLMError("quota")])
    assert not (video_dir / "reframe" / "01.json").exists()


# --------------------------------------------------------------------------
# single : suivi du visage, cadre 9:16 plein ecran
# --------------------------------------------------------------------------


def test_single_static_face_gives_a_centered_full_height_crop(tmp_path, video_dir):
    out, _, _ = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)])
    [plan] = load(out)["plans"]
    assert plan["layout"] == "single"
    assert plan["reason"] is None
    [r] = rects(plan)  # visage immobile : un seul rectangle pour tout le plan
    assert (r["x"], r["y"], r["w"], r["h"]) == (896, 0, CROP_W, 1080)
    assert (r["start"], r["end"]) == (10.0, 14.0)
    [panel] = plan["panels"]
    assert panel["dest"] == {"x": 0, "y": 0, "w": 1080, "h": 1920}


def test_single_face_at_the_edge_clamps_the_crop_inside_the_frame(tmp_path, video_dir):
    out, _, _ = run(tmp_path, static((1750, 300, 1910, 480)), [single(0)])
    [r] = rects(load(out)["plans"][0])
    assert (r["x"], r["w"]) == (W - CROP_W, CROP_W)


def test_single_jittering_face_does_not_move_the_crop(tmp_path, video_dir):
    def jitter(t):
        dx = 15 if int(t * 5) % 2 else -15
        return [(860 + dx, 300, 1060 + dx, 500)]

    out, _, _ = run(tmp_path, jitter, [single(0)])
    plan = load(out)["plans"][0]
    assert len({r["x"] for r in rects(plan)}) == 1
    for r in rects(plan):
        for t in times_in(r):
            assert contains(r, jitter(t)[0])


def test_single_moving_face_is_followed_smoothly_and_never_cut(tmp_path, video_dir):
    def moving(t):
        x = 300 + (t - 10.0) * 275  # 300 -> 1400 en 4 s
        return [(x, 300, x + 200, 500)]

    out, _, _ = run(tmp_path, moving, [single(0)])
    plan = load(out)["plans"][0]
    rs = rects(plan)
    assert len(rs) > 3
    assert_covers(rs, 10.0, 14.0)
    xs = [r["x"] for r in rs]
    assert xs == sorted(xs)  # suivi lisse : pas d'aller-retour
    assert max(b - a for a, b in zip(xs, xs[1:])) <= 120
    for r in rs:
        assert (r["w"], r["h"]) == (CROP_W, 1080)
        for t in times_in(r):
            assert contains(r, moving(t)[0]), (r, t)


def test_single_fast_face_stays_whole_between_analysed_frames(tmp_path, video_dir):
    # 700 px/s : 70 px parcourus entre une image analysee et le bord de son
    # intervalle, bien plus que la marge ; le cadre doit l'anticiper.
    def fast(t):
        x = 100 + (t - 10.0) * 700
        return [(x, 300, x + 150, 450)]

    out, _, _ = run(tmp_path, fast, [single(0)], start=10.0, end=12.0, face_margin=0.0)
    for r in rects(load(out)["plans"][0]):
        for t in times_in(r, n=9):
            assert contains(r, fast(t)[0]), (r, t)


def test_face_margin_keeps_room_around_a_face_pushed_to_the_crop_edge(tmp_path, video_dir):
    # Le visage 1 (a droite) force le bord droit du cadre pres du visage 0.
    a, b = (700, 300, 900, 500), (1000, 300, 1200, 500)
    out, _, _ = run(tmp_path, static(a, b), [single(0)], face_margin=0.15)
    [r] = rects(load(out)["plans"][0])
    x0, x1 = r["x"], r["x"] + r["w"]
    # a entier dedans, marge comprise ; b entier dehors ou entier dedans,
    # marge comprise dans les deux cas.
    assert x0 <= 700 - 30 and x1 >= 900 + 30
    assert x1 <= 1000 - 30 or (x0 <= 1000 - 30 and x1 >= 1200 + 30)


def test_single_face_missed_by_the_detector_on_some_frames_stays_in_frame(tmp_path, video_dir):
    # Visage large (48 px de jeu dans le cadre) qui se deplace, rate
    # pendant 0.8 s : le cadre doit suivre sa position interpolee.
    def moving(t):
        x = 100 + (t - 10.0) * 300
        return [(x, 300, x + 500, 800)]

    def flaky(t):
        return [] if 11.2 < t < 12.0 else moving(t)

    out, _, _ = run(tmp_path, flaky, [single(0)], face_margin=0.0)
    for r in rects(load(out)["plans"][0]):
        for t in times_in(r):
            assert contains(r, moving(t)[0]), (r, t)


def test_single_other_face_is_never_cut(tmp_path, video_dir):
    # Suivre le visage 0 en le centrant couperait le visage 1 (a sa droite).
    boxes = static((700, 300, 900, 500), (1000, 300, 1250, 550))
    out, _, _ = run(tmp_path, boxes, [single(0)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "single"
    for r in rects(plan):
        assert contains(r, (700, 300, 900, 500))
        for box in boxes(0):
            assert not cuts(r, box)


def test_single_without_face_centers_the_crop(tmp_path, video_dir):
    out, _, fake = run(tmp_path, static(), [single(None)])
    plan = load(out)["plans"][0]
    [r] = rects(plan)
    assert (r["x"], r["w"]) == (656, CROP_W)
    assert plan["faces"] == []
    assert len(fake.calls) == 1


def test_brief_false_detection_is_ignored(tmp_path, video_dir):
    face = (1100, 300, 1300, 500)

    def boxes(t):
        # Une seule image avec un faux visage a cheval sur le bord gauche du cadre.
        return [face, (850, 300, 950, 400)] if 12.0 <= t < 12.2 else [face]

    out, _, _ = run(tmp_path, boxes, [single(0)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "single"
    assert len(plan["faces"]) == 1


# --------------------------------------------------------------------------
# facecam_gameplay : camera en haut, jeu en bas
# --------------------------------------------------------------------------


def test_facecam_gameplay_stacks_camera_over_gameplay(tmp_path, video_dir):
    face = (1560, 800, 1680, 940)
    out, _, _ = run(tmp_path, static(face), [facecam(0.75, 0.7, 0.25, 0.3)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "facecam_gameplay"
    panels = {p["name"]: p for p in plan["panels"]}
    assert set(panels) == {"camera", "gameplay"}
    assert panels["camera"]["dest"] == {"x": 0, "y": 0, "w": 1080, "h": 768}
    assert panels["gameplay"]["dest"] == {"x": 0, "y": 768, "w": 1080, "h": 1152}

    zone = (1440, 756, 1920, 1080)
    for r in panels["camera"]["rects"]:
        assert contains(r, zone)
        assert contains(r, face)
        assert r["x"] >= 0 and r["y"] >= 0 and r["x"] + r["w"] <= W and r["y"] + r["h"] <= H
        assert r["w"] / r["h"] == pytest.approx(1080 / 768, rel=0.01)
    for r in panels["gameplay"]["rects"]:
        assert (r["w"], r["h"]) == (1012, 1080)
        assert not cuts(r, face)
    assert_covers(panels["camera"]["rects"], 10.0, 14.0)
    assert_covers(panels["gameplay"]["rects"], 10.0, 14.0)


def test_facecam_face_straddling_the_camera_zone_is_kept_whole(tmp_path, video_dir):
    face = (1400, 780, 1560, 960)  # centre dans la zone camera, bord gauche dehors
    out, _, _ = run(tmp_path, static(face), [facecam(0.75, 0.7, 0.25, 0.3)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "facecam_gameplay"
    [r] = rects(plan, "camera")
    assert contains(r, face)
    assert r["w"] / r["h"] == pytest.approx(1080 / 768, rel=0.01)


def test_facecam_panel_that_would_cut_another_face_falls_back(tmp_path, video_dir):
    # Un visage du jeu, hors zone camera, a cheval sur le bord du panneau camera.
    face = (1300, 800, 1500, 1000)
    out, _, _ = run(tmp_path, static(face), [facecam(0.75, 0.7, 0.25, 0.3)])
    plan = load(out)["plans"][0]
    assert plan["layout"] != "facecam_gameplay"
    assert plan["reason"]
    for panel in plan["panels"]:
        for r in panel["rects"]:
            assert not cuts(r, face)


def test_facecam_ratio_is_configurable(tmp_path, video_dir):
    out, _, _ = run(tmp_path, static((1560, 800, 1680, 940)), [facecam(0.75, 0.7, 0.25, 0.3)],
                    facecam_height_ratio=0.5)
    panels = {p["name"]: p for p in load(out)["plans"][0]["panels"]}
    assert panels["camera"]["dest"]["h"] == 960
    assert panels["gameplay"]["dest"] == {"x": 0, "y": 960, "w": 1080, "h": 960}


# --------------------------------------------------------------------------
# Replis : visages impossibles a garder entiers dans un seul cadre 9:16
# --------------------------------------------------------------------------


def test_face_too_wide_for_the_frame_falls_back_to_blur(tmp_path, video_dir):
    out, _, _ = run(tmp_path, static((500, 100, 1300, 1000)), [single(0)])
    data = load(out)
    plan = data["plans"][0]
    assert plan["layout"] == "fallback_blur"
    assert plan["reason"]
    assert data["layout"] == "fallback_blur"
    panels = {p["name"]: p for p in plan["panels"]}
    assert panels["background"]["effect"] == "blur"
    assert panels["background"]["dest"] == {"x": 0, "y": 0, "w": 1080, "h": 1920}
    [bg] = panels["background"]["rects"]
    [main] = panels["main"]["rects"]
    for r in (bg, main):
        assert (r["x"], r["y"], r["w"], r["h"]) == (0, 0, W, H)
    assert panels["main"]["dest"] == {"x": 0, "y": 656, "w": 1080, "h": 608}


def test_two_faces_that_cannot_share_a_frame_fall_back_to_split(tmp_path, video_dir):
    # Garder le visage 0 entier impose au bord droit du cadre de tomber
    # dans le visage 1 : impossible sans couper l'un des deux.
    a, b = (100, 300, 300, 500), (350, 250, 800, 700)
    out, _, _ = run(tmp_path, static(a, b), [single(0)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "split"
    assert plan["reason"]
    panels = {p["name"]: p for p in plan["panels"]}
    assert panels["top"]["dest"] == {"x": 0, "y": 0, "w": 1080, "h": 960}
    assert panels["bottom"]["dest"] == {"x": 0, "y": 960, "w": 1080, "h": 960}
    for r in panels["top"]["rects"]:
        assert contains(r, a) and not cuts(r, b)
    for r in panels["bottom"]["rects"]:
        assert contains(r, b) and not cuts(r, a)
        assert r["w"] / r["h"] == pytest.approx(1080 / 960, rel=0.01)


# --------------------------------------------------------------------------
# Doublons, pistes fragmentees et visages retenus. Donnees synthetiques
# reprenant un essai reel (source 1920x1080, 5 images/s) : le detecteur
# plein cadre + tuiles rend deux boites quasi identiques par visage, une
# fausse detection (torse) clignote sous le visage avec des trous de plus
# d'une seconde, et une piste fantome dure 0,4 s (3 images).
# --------------------------------------------------------------------------


def test_duplicate_detections_within_a_frame_are_one_face(tmp_path, video_dir):
    face, dup = (1100, 300, 1300, 500), (1090, 310, 1290, 510)  # IoU ~0.82
    out, _, _ = run(tmp_path, static(face, dup), [single(0)])
    plan = load(out)["plans"][0]
    assert len(plan["faces"]) == 1
    assert plan["layout"] == "single"


def test_duplicate_iou_threshold_is_configurable(tmp_path, video_dir):
    face, dup = (1100, 300, 1300, 500), (1090, 310, 1290, 510)
    out, _, _ = run(tmp_path, static(face, dup), [single(0)], duplicate_iou=0.9)
    assert len(load(out)["plans"][0]["faces"]) == 2


def test_track_fragments_following_each_other_in_space_are_one_face(tmp_path, video_dir):
    # Meme visage, perdu 1,8 s (plus que le trou tolere par le suivi).
    box = (1100, 300, 1300, 500)
    out, _, _ = run(tmp_path, lambda t: [] if 11.0 < t < 12.6 else [box], [single(0)])
    [face] = load(out)["plans"][0]["faces"]
    assert face["first"] == pytest.approx(10.1)
    assert face["last"] == pytest.approx(13.9)


def test_flickering_false_detection_under_the_face_is_not_protected(tmp_path, video_dir):
    # Essai reel, plan 0 : visage detecte sur toutes les images (en double),
    # torse detecte sur 8 images sur 20 en deux salves separees de 1,8 s ;
    # le torse, plus large que le cadre une fois ajoute au visage, rendait
    # le suivi impossible (split avec deux fois le plan entier).
    face, dup = (520, 160, 820, 460), (505, 175, 800, 470)
    torso = (330, 450, 850, 990)

    def boxes(t):
        flicker = 10.4 < t < 11.0 or 12.6 < t < 13.6
        return [face, dup] + ([torso] if flicker else [])

    # Numerotes de gauche a droite : #0 = torse, #1 = visage.
    out, _, _ = run(tmp_path, boxes, [single(1)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "single", plan["reason"]
    assert len(plan["faces"]) == 2  # visage (doublon fusionne) + torse (salves fusionnees)
    assert {f["id"]: f["retained"] for f in plan["faces"]} == {0: False, 1: True}
    assert plan["faces"][1]["box"][1] < 300  # le visage, pas le torse
    for r in rects(plan):
        assert (r["w"], r["h"]) == (CROP_W, 1080)
        for t in times_in(r):
            assert contains(r, face)


def test_ghost_track_of_0_4_s_is_not_protected(tmp_path, video_dir):
    # Essai reel, plan 4 : une piste de 3 images (0,4 s) passe le filtre
    # min_track_seconds et, inevitable, bloquait le suivi du visage.
    face, ghost = (1100, 300, 1300, 500), (750, 600, 1100, 950)
    out, _, _ = run(tmp_path, lambda t: [face, ghost] if 12.0 < t < 12.6 else [face], [single(1)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "single", plan["reason"]
    faces = {f["id"]: f for f in plan["faces"]}
    assert faces[1]["retained"] and not faces[0]["retained"]
    assert faces[0]["last"] - faces[0]["first"] == pytest.approx(0.4)
    for r in rects(plan):
        assert contains(r, face)


def test_small_face_is_not_protected(tmp_path, video_dir):
    # Un visage de 30 px (2,8 % de la hauteur) au bord du cadre centre : il
    # ne deplace plus le cadre.
    face, tiny = (1100, 300, 1300, 500), (1500, 300, 1530, 330)
    out, _, _ = run(tmp_path, static(face, tiny), [single(0)])
    plan = load(out)["plans"][0]
    [r] = rects(plan)
    assert (r["x"], r["w"]) == (896, CROP_W)
    assert [f["retained"] for f in plan["faces"]] == [True, False]


def test_retention_thresholds_are_configurable(tmp_path, video_dir):
    face, tiny = (1100, 300, 1300, 500), (1500, 300, 1530, 330)
    out, _, _ = run(tmp_path, static(face, tiny), [single(0)], min_face_height=0.02)
    assert [f["retained"] for f in load(out)["plans"][0]["faces"]] == [True, True]

    box = (1100, 300, 1300, 500)
    out, _, _ = run(tmp_path, lambda t: [box] if t < 11.0 else [], [single(0)], force=True,
                    min_face_presence=0.1)
    assert [f["retained"] for f in load(out)["plans"][0]["faces"]] == [True]


def test_split_is_never_made_of_one_face_and_its_duplicate(tmp_path, video_dir):
    # Visage trop large pour le cadre, detecte en double : un seul visage
    # retenu, donc pas d'ecran partage (il y mettrait deux fois la meme
    # personne) mais le fond flou.
    face, dup = (500, 100, 1300, 1000), (510, 110, 1290, 990)
    out, _, _ = run(tmp_path, static(face, dup), [single(0)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "fallback_blur"
    assert "split impossible" in plan["reason"]


def test_split_panels_each_frame_their_own_face(tmp_path, video_dir):
    # Deux visages distincts retenus que nul cadre 9:16 pleine hauteur ne
    # garde entiers : chaque panneau est cadre sur son visage, a sa taille
    # (split_face_height), et n'y met pas l'autre quand c'est possible.
    a, b = (300, 20, 450, 170), (350, 600, 1000, 1060)
    out, _, _ = run(tmp_path, static(a, b), [single(0)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "split"
    panels = {p["name"]: p for p in plan["panels"]}
    [top] = panels["top"]["rects"]
    [bottom] = panels["bottom"]["rects"]
    assert contains(top, a)
    assert not cuts(top, b) and not contains(top, b)  # b entierement dehors
    assert top["h"] < H  # zoome sur son visage
    assert (a[3] - a[1]) / top["h"] == pytest.approx(0.35, abs=0.01)
    assert contains(bottom, b) and not cuts(bottom, a)
    for r in (top, bottom):
        assert r["w"] / r["h"] == pytest.approx(1080 / 960, rel=0.01)
        assert r["x"] >= 0 and r["y"] >= 0 and r["x"] + r["w"] <= W and r["y"] + r["h"] <= H


def test_fallback_blur_is_used_when_configured(tmp_path, video_dir):
    a, b = (100, 300, 300, 500), (350, 250, 800, 700)
    out, _, _ = run(tmp_path, static(a, b), [single(0)], fallback="blur")
    assert load(out)["plans"][0]["layout"] == "fallback_blur"


def test_facecam_whose_face_cannot_fit_the_camera_panel_falls_back(tmp_path, video_dir):
    # Le visage deborde largement de la zone camera annoncee : le panneau
    # camera (1080x768) ne peut pas le contenir sans couper un autre visage.
    out, _, _ = run(tmp_path, static((200, 50, 1900, 1050)), [facecam(0.75, 0.7, 0.25, 0.3)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "fallback_blur"
    assert plan["reason"]


def test_clip_layout_is_the_one_covering_most_of_the_clip(tmp_path, video_dir):
    write_scenes(video_dir, [(0.0, 11.0), (11.0, 30.0)])
    out, _, _ = run(tmp_path, static((1100, 300, 1300, 500)), [facecam(0.75, 0.7, 0.25, 0.3), single(0)])
    data = load(out)
    assert [p["layout"] for p in data["plans"]] == ["facecam_gameplay", "single"]
    assert data["layout"] == "single"


# --------------------------------------------------------------------------
# Detecteur mediapipe : modele .tflite, jamais telecharge par les tests
# --------------------------------------------------------------------------


def test_mediapipe_model_missing_without_url_is_an_error(tmp_path):
    from clipper.reframe import CONFIG_DEFAULTS, ReframeError, ensure_mediapipe_model

    settings = {**CONFIG_DEFAULTS, "model_path": str(tmp_path / "absent.tflite"), "model_url": ""}
    with pytest.raises(ReframeError, match="absent.tflite"):
        ensure_mediapipe_model(settings)


def test_mediapipe_model_missing_is_fetched_once_from_model_url(tmp_path):
    from clipper.reframe import CONFIG_DEFAULTS, ensure_mediapipe_model

    fetched = []

    def fetch(url, dest):
        fetched.append(url)
        Path(dest).write_bytes(b"tflite")

    target = tmp_path / "models" / "face.tflite"
    settings = {**CONFIG_DEFAULTS, "model_path": str(target), "model_url": "https://example.invalid/face.tflite"}
    assert ensure_mediapipe_model(settings, fetch=fetch) == target
    assert ensure_mediapipe_model(settings, fetch=fetch) == target
    assert fetched == ["https://example.invalid/face.tflite"]
    assert target.read_bytes() == b"tflite"


@pytest.mark.skipif(
    os.environ.get("CLIPPER_REAL_MODELS") != "1",
    reason="vrai modele mediapipe : CLIPPER_REAL_MODELS=1 (telecharge le .tflite si absent)",
)
def test_real_mediapipe_detector_runs_on_cpu():
    from clipper.reframe import CONFIG_DEFAULTS, mediapipe_detector

    detector = mediapipe_detector(dict(CONFIG_DEFAULTS), Device(type="cpu", compute_type="int8"))
    try:
        assert detector.detect(np.zeros((H, W, 3), dtype=np.uint8)) == []
    finally:
        detector.close()
