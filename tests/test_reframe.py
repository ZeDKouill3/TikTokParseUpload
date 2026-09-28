from __future__ import annotations

import json
import math
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
    # Le format par defaut de CONFIG_DEFAULTS est devenu "letterbox" (SPEC-6127) ;
    # ces tests exercent le format "crop" (code actuel, inchange), sauf demande
    # explicite d'un autre format.
    reframe.setdefault("format", "crop")
    return Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={"reframe": reframe},
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


def single(face, ignore=None):
    answer = {"layout": "single", "camera": None, "face": face, "reason": "r"}
    if ignore is not None:
        answer["ignore"] = list(ignore)
    return answer


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
# Gros plans et causes de repli de l'essai reel sZi-qJ-5ptA (1920x1080,
# 5 images/s). Detections mediapipe relevees image par image et rejouees :
# les visages suivis tenaient dans 608 px mais pas avec la marge sur la zone
# balayee (camera portee).
# --------------------------------------------------------------------------

# Clip 06, plan 2 : un seul visage, retenu, 430 a 490 px, camera qui bouge
# (180 px en 0,6 s au debut) ; zone balayee + marge 0.15 jusqu'a 722 px.
REAL_06_2 = [
    [(353, 405, 779, 831)], [(360, 316, 819, 774)], [(402, 295, 884, 777)],
    [(541, 313, 988, 760)], [(556, 304, 1009, 757)], [(535, 301, 993, 759)],
    [(525, 301, 982, 758)], [(510, 306, 967, 763)], [(514, 327, 943, 756)],
    [(475, 288, 912, 725), (720, 426, 1000, 706)], [(451, 305, 917, 771)],
    [(468, 295, 917, 744), (720, 410, 981, 671)], [(493, 314, 949, 770)],
    [(502, 315, 948, 761)], [(512, 337, 953, 778)], [(485, 310, 936, 761)],
    [(481, 405, 916, 840)], [(465, 300, 931, 766)], [(467, 405, 901, 839)],
    [(436, 308, 910, 781)], [(411, 291, 904, 784)], [(408, 302, 885, 779)],
    [(410, 309, 899, 798)],
]

# Clip 00, plan 1, de 696,73 a 699,35 s : visage retenu de 480 a 550 px qui
# traverse l'image (520 px en 2 s), zone balayee + marge jusqu'a 787 px ;
# fausses detections a gauche sur les 3 dernieres images.
REAL_00_1 = [
    [(548, 86, 1032, 570)], [(543, 123, 1043, 623)], [(606, 132, 1095, 621)],
    [(624, 133, 1147, 656)], [(722, 138, 1240, 656)], [(771, 127, 1317, 673)],
    [(800, 83, 1332, 615)], [(837, 133, 1338, 634)], [(859, 141, 1362, 644)],
    [(889, 120, 1397, 628)], [(985, 152, 1413, 580)],
    [(1050, 120, 1493, 563), (176, 288, 469, 581)],
    [(1074, 175, 1470, 571), (61, 405, 641, 985)],
    [(1081, 172, 1441, 532), (320, 409, 635, 724)],
]


def replay(frames, start=10.0):
    """Detections image par image, une image analysee toutes les 0,2 s a
    partir de ``start`` (sample_fps = 5) ; renvoie aussi la fin du plan."""

    def boxes(t):
        return list(frames[round((t - start - 0.1) / 0.2)])

    return boxes, start + 0.2 * len(frames)


def analysed_times(start, end, fps=5.0):
    count = int((end - start) * fps + 1e-9)
    return [start + (k + 0.5) * (end - start) / count for k in range(count)]


def rect_at(rs, t):
    [r] = [r for r in rs if r["start"] <= t < r["end"]]
    return r


def assert_single_keeps_face_whole(plan, face_at, start, end):
    """single, sans repli, et le visage suivi entier dans le cadre a chaque
    image analysee."""
    assert plan["layout"] == "single", plan["reason"]
    assert plan["reason"] is None
    rs = rects(plan)
    assert_covers(rs, start, end)
    for t in analysed_times(start, end):
        box = face_at(t)
        if box is not None:
            r = rect_at(rs, t)
            assert (r["w"], r["h"]) == (CROP_W, 1080)
            assert contains(r, box), (t, r, box)


# (1) Visage suivi retenu : marge reduite puis boite instantanee, jamais rogne.


@pytest.mark.parametrize("frames", [REAL_06_2, REAL_00_1], ids=["06-2", "00-1"])
def test_real_close_up_with_moving_camera_is_framed_single(tmp_path, video_dir, frames):
    boxes, end = replay(frames)
    out, _, _ = run(tmp_path, boxes, [single(None)], start=10.0, end=end)
    [face] = [f for f in load(out)["plans"][0]["faces"] if f["retained"]]
    out, _, _ = run(tmp_path, boxes, [single(face["id"])], start=10.0, end=end, force=True)
    # Le visage suivi : la boite la plus haute de chaque image (les fausses
    # detections sont dessous).
    topmost = lambda t: min(boxes(t), key=lambda b: b[1])  # noqa: E731
    assert_single_keeps_face_whole(load(out)["plans"][0], topmost, 10.0, end)


def test_close_up_of_486_px_with_camera_moving_is_framed_single(tmp_path, video_dir):
    # Clip 10, plan 3 : visage de 486 px ; la camera oscille de +-60 px, la
    # zone balayee + marge 0.15 depasse le cadre de 608 px.
    def face(t):
        x = 777 + 60 * math.sin(math.pi * (t - 10.0))
        return (x, 112, x + 486, 601)

    out, _, _ = run(tmp_path, lambda t: [face(t)], [single(0)])
    assert_single_keeps_face_whole(load(out)["plans"][0], face, 10.0, 14.0)


def test_close_up_keeps_the_largest_margin_that_fits(tmp_path, video_dir):
    # Visage immobile de 486 px : 632 px avec la marge 0.15, il tient avec
    # une marge reduite, gardee aussi grande que possible (0.1).
    face = (777, 112, 1263, 601)
    out, _, _ = run(tmp_path, static(face), [single(0)])
    plan = load(out)["plans"][0]
    assert_single_keeps_face_whole(plan, lambda t: face, 10.0, 14.0)
    [r] = rects(plan)
    assert r["x"] <= 777 - 0.1 * 486 and r["x"] + r["w"] >= 1263 + 0.1 * 486


def test_face_wider_than_the_frame_is_never_cropped(tmp_path, video_dir):
    # 625 px pour un cadre de 608 : aucun palier ne le garde entier, repli
    # (SPEC-350f : aucun visage coupe) ; la raison nomme le dernier palier.
    out, _, _ = run(tmp_path, static((455, 300, 1080, 925)), [single(0)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "fallback_blur"
    assert "dernier palier : boite instantanee" in plan["reason"]


def test_other_retained_face_is_never_cut_by_a_degraded_frame(tmp_path, video_dir):
    # Gros plan de 600 px (boite instantanee seulement) et un visage retenu
    # juste a droite : le cadre garde le gros plan et laisse l'autre entier
    # dehors, marge 0.15 comprise.
    a, b = (500, 240, 1100, 840), (1130, 300, 1330, 500)
    out, _, _ = run(tmp_path, static(a, b), [single(0)])
    plan = load(out)["plans"][0]
    assert plan["layout"] == "single", plan["reason"]
    assert [f["retained"] for f in plan["faces"]] == [True, True]
    for r in rects(plan):
        assert contains(r, a)
        assert not cuts(r, (1130 - 30, 300 - 30, 1330 + 30, 500 + 30))


def test_two_retained_faces_inevitably_cut_fall_back_to_blur(tmp_path, video_dir):
    # Gros plan de 600 px chevauche par un autre visage retenu : aucun
    # palier ne cadre l'un sans couper l'autre, ni l'ecran partage.
    a, b = (300, 200, 900, 800), (850, 250, 1600, 850)
    out, _, _ = run(tmp_path, static(a, b), [single(0)])
    plan = load(out)["plans"][0]
    assert [f["retained"] for f in plan["faces"]] == [True, True]
    assert plan["layout"] == "fallback_blur"
    assert "dernier palier : boite instantanee" in plan["reason"]
    assert "split impossible" in plan["reason"]


# (2) Le LLM ne suit qu'un visage retenu.


def test_prompt_says_which_faces_are_retained(tmp_path, video_dir):
    face, tiny = (1100, 300, 1300, 500), (1500, 300, 1530, 330)
    _, _, fake = run(tmp_path, static(face, tiny), [single(0)])
    prompt = fake.calls[0].prompt
    [line0] = [line for line in prompt.splitlines() if line.startswith("- #0 ")]
    [line1] = [line for line in prompt.splitlines() if line.startswith("- #1 ")]
    assert "non retenu" not in line0 and "retenu" in line0
    assert "non retenu" in line1


def test_llm_choosing_a_face_not_retained_is_a_schema_error(tmp_path, video_dir):
    # #1 : visage de 30 px, non retenu ; le suivre est une reponse invalide.
    face, tiny = (1100, 300, 1300, 500), (1500, 300, 1530, 330)
    with pytest.raises(llm.SchemaError, match="#1"):
        run(tmp_path, static(face, tiny), [single(1)])
    assert not (video_dir / "reframe" / "01.json").exists()


# (3) Faux positifs designes par le LLM (main, objet) : ni retenus ni proteges.


def test_ignored_detection_no_longer_constrains_the_frame(tmp_path, video_dir):
    # Une main retenue (#0) a gauche du visage (#1), a cheval sur le cadre
    # centre sur lui : sans ignore, le cadre se decale pour la garder
    # entiere ; avec ignore, il est centre sur le visage.
    hand, face = (700, 600, 900, 800), (1000, 300, 1200, 500)
    out, _, _ = run(tmp_path, static(hand, face), [single(1)])
    [r] = rects(load(out)["plans"][0])
    assert r["x"] != 796

    out, _, _ = run(tmp_path, static(hand, face), [single(1, ignore=[0])], force=True)
    plan = load(out)["plans"][0]
    assert plan["layout"] == "single"
    assert {f["id"]: f["retained"] for f in plan["faces"]} == {0: False, 1: True}
    [r] = rects(plan)
    assert (r["x"], r["w"]) == (796, CROP_W)


def test_ignore_must_name_detected_faces_and_never_the_followed_one(tmp_path, video_dir):
    face = (1100, 300, 1300, 500)
    with pytest.raises(llm.SchemaError):
        run(tmp_path, static(face), [single(0, ignore=[5])])
    with pytest.raises(llm.SchemaError):
        run(tmp_path, static(face), [single(0, ignore=[0])])


# (4) Presence mesuree sur la duree de la piste.


def test_face_entering_mid_plan_is_retained(tmp_path, video_dir):
    # Visage vu de 12 a 14 s sur un plan de 10 a 14 s : moitie du plan, mais
    # toute la duree de sa piste.
    late = (500, 300, 700, 500)
    out, _, _ = run(tmp_path, lambda t: [late] if t > 12.0 else [], [single(0)])
    [face] = load(out)["plans"][0]["faces"]
    assert face["retained"]


# Splits trop courts et plans parasites.


def test_split_shorter_than_split_min_seconds_falls_back_to_blur(tmp_path, video_dir):
    a, b = (100, 300, 300, 500), (350, 250, 800, 700)
    out, _, _ = run(tmp_path, static(a, b), [single(0)], start=10.0, end=11.0)
    plan = load(out)["plans"][0]
    assert [f["retained"] for f in plan["faces"]] == [True, True]
    assert plan["layout"] == "fallback_blur"
    assert "split_min_seconds" in plan["reason"]

    # Configurable : 1 s suffit a un split si split_min_seconds le permet.
    out, _, _ = run(tmp_path, static(a, b), [single(0)], start=10.0, end=11.0, force=True,
                    split_min_seconds=1.0)
    assert load(out)["plans"][0]["layout"] == "split"


def test_plan_shorter_than_min_plan_seconds_is_merged_into_its_neighbour(tmp_path, video_dir):
    write_scenes(video_dir, [(0.0, 12.0), (12.0, 12.08), (12.08, 30.0)])
    out, _, fake = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)] * 2, start=10.0, end=14.0)
    data = load(out)
    assert [(p["start"], p["end"]) for p in data["plans"]] == [(10.0, 12.08), (12.08, 14.0)]
    assert [p["index"] for p in data["plans"]] == [0, 1]
    assert len(fake.calls) == 2


def test_clip_edge_sliver_is_merged_into_the_next_plan(tmp_path, video_dir):
    write_scenes(video_dir, [(0.0, 10.1), (10.1, 30.0)])
    out, _, fake = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)], start=10.0, end=14.0)
    assert [(p["start"], p["end"]) for p in load(out)["plans"]] == [(10.0, 14.0)]
    assert len(fake.calls) == 1


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


# --------------------------------------------------------------------------
# Format letterbox (SPEC-6127) : zoom fixe, fond flou, aucun visage suivi,
# aucun appel LLM.
# --------------------------------------------------------------------------


def letterbox_plan(data):
    [plan] = data["plans"]
    return plan


def letterbox_panels(plan):
    return {p["name"]: p for p in plan["panels"]}


def test_letterbox_default_geometry_for_a_1920x1080_source(tmp_path, video_dir):
    out, factory, fake = run(tmp_path, static(), [], format="letterbox")

    data = load(out)
    assert data["video_id"] == VIDEO_ID
    assert data["clip_id"] == "01"
    assert (data["start"], data["end"]) == (10.0, 14.0)
    assert data["source"] == {"width": W, "height": H}
    assert data["output"] == {"width": 1080, "height": 1920}
    assert data["layout"] == "letterbox"
    assert data["format"] == "letterbox"
    assert data["text_zones"] == {
        "title": {"x0": 150, "y0": 160, "x1": 930, "y1": 424},
        "subtitles": {"x0": 150, "y0": 1246, "x1": 930, "y1": 1448},
        "part": {"x0": 150, "y0": 1464, "x1": 930, "y1": 1520},
    }

    plan = letterbox_plan(data)
    assert plan["index"] == 0
    assert (plan["start"], plan["end"]) == (10.0, 14.0)
    assert plan["image"] is None
    assert plan["llm"] is None
    assert plan["layout"] == "letterbox"
    assert plan["reason"] is None
    assert plan["faces"] == []
    assert [p["name"] for p in plan["panels"]] == ["background", "main"]

    panels = letterbox_panels(plan)
    assert panels["background"]["effect"] == "blur"
    assert panels["background"]["dest"] == {"x": 0, "y": 0, "w": 1080, "h": 1920}
    [bg] = panels["background"]["rects"]
    assert (bg["start"], bg["end"], bg["x"], bg["y"], bg["w"], bg["h"]) == (10.0, 14.0, 0, 0, W, H)

    assert panels["main"]["dest"] == {"x": 0, "y": 440, "w": 1080, "h": 790}
    [main] = panels["main"]["rects"]
    assert (main["start"], main["end"], main["x"], main["y"], main["w"], main["h"]) == (10.0, 14.0, 222, 0, 1476, 1080)

    # Aucune detection de visage, aucun detecteur construit, aucun appel LLM.
    assert factory.built == []
    assert fake.calls == []


def test_letterbox_window_for_a_1280x720_source(tmp_path, video_dir):
    out, _, _ = run(tmp_path, static(), [], format="letterbox", video=FakeVideo(width=1280, height=720))

    plan = letterbox_plan(load(out))
    panels = letterbox_panels(plan)
    assert panels["main"]["dest"] == {"x": 0, "y": 440, "w": 1080, "h": 790}
    [main] = panels["main"]["rects"]
    assert (main["x"], main["y"], main["w"], main["h"]) == (148, 0, 984, 720)


def test_letterbox_zones_that_do_not_fit_are_an_error(tmp_path, video_dir):
    from clipper.reframe import ReframeError

    with pytest.raises(ReframeError):
        run(tmp_path, static(), [], format="letterbox", video=FakeVideo(width=1440, height=1080))


def test_letterbox_zoom_below_one_is_an_error(tmp_path, video_dir):
    from clipper.reframe import ReframeError

    with pytest.raises(ReframeError, match="zoom"):
        run(tmp_path, static(), [], format="letterbox", letterbox_zoom=0.9)


def test_unknown_reframe_format_is_an_error(tmp_path, video_dir):
    from clipper.reframe import ReframeError

    with pytest.raises(ReframeError, match="vertical"):
        run(tmp_path, static(), [], format="vertical")


def test_letterbox_does_not_require_scenes_json(tmp_path, video_dir):
    (video_dir / "scenes.json").unlink()
    out, _, _ = run(tmp_path, static(), [], format="letterbox")
    assert load(out)["layout"] == "letterbox"


def test_existing_crop_plan_with_letterbox_config_is_an_error_without_force(tmp_path, video_dir):
    from clipper.reframe import ReframeError

    out, _, _ = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)])  # format="crop" (par defaut du test)
    assert "format" not in load(out)  # ancien format crop : pas de champ "format"

    with pytest.raises(ReframeError, match="crop"):
        run(tmp_path, static(), [], format="letterbox")

    out2, factory, fake = run(tmp_path, static(), [], format="letterbox", force=True)
    assert out2 == out
    assert load(out2)["format"] == "letterbox"
    assert factory.built == [] and fake.calls == []


def test_existing_letterbox_plan_with_crop_config_is_an_error_without_force(tmp_path, video_dir):
    from clipper.reframe import ReframeError

    out, _, _ = run(tmp_path, static(), [], format="letterbox")

    with pytest.raises(ReframeError, match="letterbox"):
        run(tmp_path, static((1100, 300, 1300, 500)), [single(0)], format="crop")

    out2, _, fake = run(tmp_path, static((1100, 300, 1300, 500)), [single(0)], format="crop", force=True)
    assert out2 == out
    assert len(fake.calls) == 1
    assert "format" not in load(out2)
