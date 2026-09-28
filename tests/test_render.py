from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from clipper.config import Config

VIDEO_ID = "abcdefghijk"
CLIP_ID = "03"
SRC_W, SRC_H = 1920, 1080
OUT_W, OUT_H = 1080, 1920
CROP_W = 608  # cadre 9:16 pleine hauteur dans une source 1920x1080

no_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent du PATH")
no_ffprobe = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe absent du PATH")


def make_config(**render_settings):
    return Config(mode="review", workspace_dir=Path("workspace"), output_dir=Path("output"),
                  _sections={"render": render_settings} if render_settings else {})


# --------------------------------------------------------------------------
# Fixtures : arborescence workspace/<video_id>/ realiste (sorties reelles des
# etapes dont depend render, jamais importees - ADR-b16b).
# --------------------------------------------------------------------------


def _captions_json(**overrides):
    clip = {
        "id": CLIP_ID,
        "moment_id": 3,
        "part": 1,
        "parts_total": 1,
        "start": 1.0,
        "end": 3.5,
        "duration": 2.5,
        "language": "fr",
        "title": "Titre du clip",
        "caption": "Une legende qui donne envie",
        "hashtags": ["#gta6", "#trailer"],
        "hook_text": "Attends de voir ca",
        "screen_title": "Il m'a menti en garde à vue",
    }
    clip.update(overrides)
    return {"video_id": VIDEO_ID, "clips": [clip]}


def _moments_json():
    return {
        "video_id": VIDEO_ID,
        "rubric": {"path": "rubric.toml", "weights": {}, "min_score": 60},
        "moments": [
            {
                "id": 3,
                "start": 1.0,
                "end": 3.5,
                "duration": 2.5,
                "format": "single",
                "parts": [],
                "scores": {"hook": 8, "standalone": 7, "payoff": 6, "emotion": 5, "value": 6, "trend": 9},
                "bonus": 4.0,
                "final_score": 78.5,
                "justification": "Revelation choc sur GTA 6",
                "hook_text": "Attends de voir ca",
            }
        ],
        "rejected": [],
    }


def _transcript_json():
    words = [
        {"word": "Attends ", "start": 1.0, "end": 1.4},
        {"word": "de ", "start": 1.4, "end": 1.6},
        {"word": "voir ", "start": 1.6, "end": 1.9},
        {"word": "ca.", "start": 1.9, "end": 2.2},
        {"word": "Incroyable.", "start": 2.5, "end": 3.4},
    ]
    return {
        "language": "fr",
        "segments": [
            {"start": 1.0, "end": 2.2, "text": "Attends de voir ca.", "words": words[:4]},
            {"start": 2.5, "end": 3.4, "text": "Incroyable.", "words": words[4:]},
        ],
    }


def _meta_json():
    return {"video_id": VIDEO_ID, "title": "Une video source"}


def _panel(name, x, y, w, h, dest, effect=None, start=1.0, end=3.5):
    panel = {"name": name, "dest": dest, "rects": [{"start": start, "end": end, "x": x, "y": y, "w": w, "h": h}]}
    if effect:
        panel["effect"] = effect
    return panel


def _reframe_json_single_plan():
    panels = [_panel("main", 656, 0, CROP_W, SRC_H, {"x": 0, "y": 0, "w": OUT_W, "h": OUT_H})]
    plan = {
        "index": 0, "start": 1.0, "end": 3.5, "image": "reframe/03/plan_000.jpg",
        "llm": {"layout": "single", "camera": None, "face": None, "reason": "plan centre"},
        "layout": "single", "reason": None, "faces": [], "panels": panels,
    }
    return {
        "video_id": VIDEO_ID, "clip_id": CLIP_ID, "start": 1.0, "end": 3.5,
        "source": {"width": SRC_W, "height": SRC_H}, "output": {"width": OUT_W, "height": OUT_H},
        "layout": "single", "plans": [plan],
    }


def _reframe_json_two_plans():
    """1er plan facecam_gameplay (camera fixe + gameplay qui bouge), 2e plan
    fallback_blur (fond floute + image entiere) : exerce crop/scale, pile
    facecam/gameplay et fond flou dans le meme clip."""
    cam_h = round(OUT_H * 0.4)
    game_h = OUT_H - cam_h
    plan0 = {
        "index": 0, "start": 1.0, "end": 2.2, "image": "x", "llm": {}, "layout": "facecam_gameplay",
        "reason": None, "faces": [],
        "panels": [
            {"name": "camera", "dest": {"x": 0, "y": 0, "w": OUT_W, "h": cam_h},
             "rects": [{"start": 1.0, "end": 2.2, "x": 700, "y": 50, "w": 400, "h": 300}]},
            {"name": "gameplay", "dest": {"x": 0, "y": cam_h, "w": OUT_W, "h": game_h},
             "rects": [
                 {"start": 1.0, "end": 1.6, "x": 0, "y": 0, "w": 960, "h": SRC_H},
                 {"start": 1.6, "end": 2.2, "x": 960, "y": 0, "w": 960, "h": SRC_H},
             ]},
        ],
    }
    plan1 = {
        "index": 1, "start": 2.2, "end": 3.5, "image": "x", "llm": {}, "layout": "fallback_blur",
        "reason": "aucun cadre ne garde les visages entiers", "faces": [],
        "panels": [
            {"name": "background", "effect": "blur", "dest": {"x": 0, "y": 0, "w": OUT_W, "h": OUT_H},
             "rects": [{"start": 2.2, "end": 3.5, "x": 0, "y": 0, "w": SRC_W, "h": SRC_H}]},
            {"name": "main", "dest": {"x": 0, "y": 391, "w": OUT_W, "h": 608},
             "rects": [{"start": 2.2, "end": 3.5, "x": 0, "y": 0, "w": SRC_W, "h": SRC_H}]},
        ],
    }
    return {
        "video_id": VIDEO_ID, "clip_id": CLIP_ID, "start": 1.0, "end": 3.5,
        "source": {"width": SRC_W, "height": SRC_H}, "output": {"width": OUT_W, "height": OUT_H},
        "layout": "facecam_gameplay", "plans": [plan0, plan1],
    }


ASS_TEXT = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Poppins ExtraBold,96,&H00FFFFFF&,&H0080FFFF&,&H00000000&,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,2,40,40,160,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{\\k100}Attends
"""


@pytest.fixture
def video_dir(tmp_path):
    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / "captions.json").write_text(json.dumps(_captions_json()), encoding="utf-8")
    (d / "moments.json").write_text(json.dumps(_moments_json()), encoding="utf-8")
    (d / "transcript.json").write_text(json.dumps(_transcript_json()), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(_meta_json()), encoding="utf-8")
    (d / "reframe").mkdir()
    (d / "reframe" / f"{CLIP_ID}.json").write_text(json.dumps(_reframe_json_single_plan()), encoding="utf-8")
    (d / "subtitles").mkdir()
    (d / "subtitles" / f"{CLIP_ID}.ass").write_text(ASS_TEXT, encoding="utf-8")
    return d


@pytest.fixture
def synthetic_source(video_dir):
    video = video_dir / f"{VIDEO_ID}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size={SRC_W}x{SRC_H}:rate=25:duration=5",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=5",
         "-ac", "2", "-shortest", str(video)],
        check=True,
    )
    return video


@pytest.fixture
def cpu_device(fake_ctranslate2):
    fake_ctranslate2(cuda_device_count=0)


def _ffprobe_json(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        stdout=subprocess.PIPE, check=True,
    )
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------
# C6/C11 : rendu ffmpeg reel, verifie par ffprobe (done_criteria)
# --------------------------------------------------------------------------


@no_ffmpeg
@no_ffprobe
def test_render_writes_1080x1920_h264_aac_mp4_matching_clip_duration(tmp_path, video_dir, synthetic_source, cpu_device):
    from clipper.render import render

    out = render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output",
                 config=make_config())

    assert out == tmp_path / "output" / VIDEO_ID / f"{CLIP_ID}.mp4"
    assert out.exists()
    probe = _ffprobe_json(out)
    streams = {s["codec_type"]: s for s in probe["streams"]}
    assert streams["video"]["width"] == OUT_W
    assert streams["video"]["height"] == OUT_H
    assert streams["video"]["codec_name"] == "h264"
    assert streams["audio"]["codec_name"] == "aac"
    assert float(probe["format"]["duration"]) == pytest.approx(2.5, abs=0.1)


@no_ffmpeg
@no_ffprobe
def test_render_converts_a_25fps_source_to_30fps_output(tmp_path, video_dir, synthetic_source, cpu_device):
    """SPEC-350f exige 30 i/s en sortie ; la source synthetique est a 25 i/s
    (constat de l'essai reel du 2026-09-25) : render doit convertir, pas
    garder la cadence source."""
    from clipper.render import render

    out = render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output",
                 config=make_config())

    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(out)],
        stdout=subprocess.PIPE, check=True,
    )
    assert proc.stdout.decode().strip() == "30/1"


def _reframe_json_full_frame_blur(duration):
    """Un seul plan, un seul panneau fond flou couvrant tout le cadre de
    sortie : maximise la part du boxblur dans le cout du rendu, pour que le
    ratio avant/apres reste mesurable sur une video courte."""
    plan = {
        "index": 0, "start": 0.0, "end": duration, "image": "x", "llm": {}, "layout": "fallback_blur",
        "reason": "aucun cadre ne garde les visages entiers", "faces": [],
        "panels": [
            {"name": "background", "effect": "blur", "dest": {"x": 0, "y": 0, "w": OUT_W, "h": OUT_H},
             "rects": [{"start": 0.0, "end": duration, "x": 0, "y": 0, "w": SRC_W, "h": SRC_H}]},
        ],
    }
    return {
        "video_id": VIDEO_ID, "clip_id": CLIP_ID, "start": 0.0, "end": duration,
        "source": {"width": SRC_W, "height": SRC_H}, "output": {"width": OUT_W, "height": OUT_H},
        "layout": "fallback_blur", "plans": [plan],
    }


def test_render_writes_conforming_output_when_a_panel_uses_fallback_blur(tmp_path, cpu_device):
    """Structure du graphe ffmpeg pour fallback_blur (sans mesure de temps,
    instable sous charge - voir le test optionnel CLIPPER_BENCH ci-dessous) :
    _build_filter_complex reduit avant boxblur puis agrandit vers dest, et le
    label de sortie chaine correctement jusqu'a l'accroche/sous-titres."""
    from clipper.render import CONFIG_DEFAULTS, _build_filter_complex

    duration = 2.5
    reframe_data = _reframe_json_full_frame_blur(duration)
    hook_path = tmp_path / "hook.txt"
    hook_path.write_text("x", encoding="utf-8")
    ass_path = tmp_path / "sub.ass"
    ass_path.write_text(ASS_TEXT, encoding="utf-8")

    filt, label = _build_filter_complex(
        reframe_data, 0.0, duration, ass_path, hook_path, None, tmp_path, CONFIG_DEFAULTS
    )

    factor = CONFIG_DEFAULTS["blur_downscale"]
    assert f"scale=iw/{factor}:ih/{factor}" in filt
    assert filt.index(f"scale=iw/{factor}:ih/{factor}") < filt.index("boxblur")
    assert filt.index("boxblur") < filt.rindex(f"scale={OUT_W}:{OUT_H}")
    assert label == "vhook"


# --------------------------------------------------------------------------
# Vitesse (mesure de temps reelle, instable sous charge machine) : optionnel,
# saute par defaut, active par CLIPPER_BENCH=1 (consigne orchestrateur
# 2026-09-28 : pas d'assertion de temps reel dans la suite par defaut).
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CLIPPER_BENCH") != "1",
    reason="mesure de vitesse reelle, instable sous charge : definir CLIPPER_BENCH=1",
)
@no_ffmpeg
@no_ffprobe
def test_render_fallback_blur_is_at_least_3x_faster_than_full_resolution_blur(tmp_path, cpu_device):
    """Constat essai reel 2026-09-25 : ~1200s CPU pour 40s de clip en
    fallback_blur, contre ~45s sans flou, a cause du boxblur plein cadre
    1080x1920. blur_downscale=1 (pas de reduction) rejoue ce cout ; le
    reglage par defaut doit rendre au moins 3 fois plus vite, a parametres
    egaux par ailleurs. Mesure en ratio (jamais un temps absolu), meilleur de
    plusieurs essais (le pire cas est un pic de charge de la machine, jamais
    un rendu plus rapide que sa vraie duree), pour rester robuste."""
    import time

    from clipper.render import render

    duration = 8.0
    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / "captions.json").write_text(
        json.dumps(_captions_json(start=0.0, end=duration, duration=duration)), encoding="utf-8"
    )
    (d / "moments.json").write_text(json.dumps(_moments_json()), encoding="utf-8")
    (d / "transcript.json").write_text(json.dumps(_transcript_json()), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(_meta_json()), encoding="utf-8")
    (d / "reframe").mkdir()
    (d / "reframe" / f"{CLIP_ID}.json").write_text(
        json.dumps(_reframe_json_full_frame_blur(duration)), encoding="utf-8"
    )
    (d / "subtitles").mkdir()
    (d / "subtitles" / f"{CLIP_ID}.ass").write_text(ASS_TEXT, encoding="utf-8")
    video = d / f"{VIDEO_ID}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size={SRC_W}x{SRC_H}:rate=25:duration={duration}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={duration}",
         "-ac", "2", "-shortest", str(video)],
        check=True,
    )

    repeats = 3
    baseline_times = []
    fast_times = []
    for i in range(repeats):
        start = time.perf_counter()
        render(
            VIDEO_ID, CLIP_ID, workspace_dir=d.parent, output_dir=tmp_path / f"output_baseline{i}",
            config=make_config(blur_downscale=1),
        )
        baseline_times.append(time.perf_counter() - start)

        start = time.perf_counter()
        render(
            VIDEO_ID, CLIP_ID, workspace_dir=d.parent, output_dir=tmp_path / f"output_fast{i}",
            config=make_config(),
        )
        fast_times.append(time.perf_counter() - start)

    # min() plutot que la moyenne : un pic de charge ne peut que ralentir un
    # essai, jamais l'accelerer, donc le minimum approxime le cout reel.
    assert min(fast_times) * 3 <= min(baseline_times)


@no_ffmpeg
@no_ffprobe
def test_render_applies_facecam_gameplay_then_fallback_blur_panels(tmp_path, video_dir, synthetic_source, cpu_device):
    """Deux plans, layouts differents (facecam/gameplay puis fond flou) :
    exerce crop/scale, pile facecam/gameplay et fond flou dans un seul rendu."""
    from clipper.render import render

    (video_dir / "reframe" / f"{CLIP_ID}.json").write_text(json.dumps(_reframe_json_two_plans()), encoding="utf-8")

    out = render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output",
                 config=make_config())

    probe = _ffprobe_json(out)
    streams = {s["codec_type"]: s for s in probe["streams"]}
    assert streams["video"]["width"] == OUT_W
    assert streams["video"]["height"] == OUT_H
    assert streams["video"]["codec_name"] == "h264"
    assert float(probe["format"]["duration"]) == pytest.approx(2.5, abs=0.1)


# --------------------------------------------------------------------------
# JSON de sortie (SPEC-350f)
# --------------------------------------------------------------------------


@no_ffmpeg
@no_ffprobe
def test_render_writes_json_sidecar_conforming_to_spec_350f(tmp_path, video_dir, synthetic_source, cpu_device):
    from clipper.render import render

    render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output", config=make_config())

    data = json.loads((tmp_path / "output" / VIDEO_ID / f"{CLIP_ID}.json").read_text(encoding="utf-8"))

    required = {
        "video_id", "source_url", "source_title", "clip_id", "part", "parts_total",
        "start", "end", "duration", "language", "score", "scores", "reason", "hook_text",
        "title", "caption", "hashtags", "transcript", "layout", "qa", "created_at",
    }
    assert required <= set(data)
    assert data["video_id"] == VIDEO_ID
    assert data["clip_id"] == CLIP_ID
    assert data["part"] == 1
    assert data["parts_total"] == 1
    assert data["start"] == 1.0
    assert data["end"] == 3.5
    assert data["duration"] == 2.5
    assert data["language"] == "fr"
    assert data["score"] == 78.5
    assert data["scores"] == {"hook": 8, "standalone": 7, "payoff": 6, "emotion": 5, "value": 6, "trend": 9}
    assert data["reason"] == "Revelation choc sur GTA 6"
    assert data["hook_text"] == "Attends de voir ca"
    assert data["title"] == "Titre du clip"
    assert data["caption"] == "Une legende qui donne envie"
    assert data["hashtags"] == ["#gta6", "#trailer"]
    assert data["layout"] == "single"
    assert data["source_title"] == "Une video source"
    assert data["source_url"] == f"https://www.youtube.com/watch?v={VIDEO_ID}"
    assert data["qa"] == {"status": "skipped", "issues": []}
    assert data["transcript"] == "Attends de voir ca.Incroyable."
    assert data["created_at"]  # horodatage ISO 8601 non vide


# --------------------------------------------------------------------------
# Cache par resultat existant (ADR-b16b)
# --------------------------------------------------------------------------


@no_ffmpeg
@no_ffprobe
def test_render_skips_ffmpeg_when_output_already_present(tmp_path, video_dir, synthetic_source, cpu_device):
    from clipper.render import render

    out_dir = tmp_path / "output"
    first = render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=out_dir, config=make_config())
    original_bytes = first.read_bytes()

    second = render(
        VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=out_dir, config=make_config(),
        ffmpeg_bin="ffmpeg-does-not-exist",
    )

    assert second == first
    assert second.read_bytes() == original_bytes


@no_ffmpeg
@no_ffprobe
def test_render_force_redoes_the_render_even_if_output_present(tmp_path, video_dir, synthetic_source, cpu_device):
    from clipper.render import render

    out_dir = tmp_path / "output"
    render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=out_dir, config=make_config())

    with pytest.raises(Exception):
        render(
            VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=out_dir, config=make_config(),
            force=True, ffmpeg_bin="ffmpeg-does-not-exist",
        )


# --------------------------------------------------------------------------
# Entrees manquantes ou incoherentes : jamais de repli silencieux (ADR-ad2e)
# --------------------------------------------------------------------------


def test_missing_source_video_is_an_error(tmp_path, video_dir):
    from clipper.render import RenderError, render

    with pytest.raises(RenderError, match=f"{VIDEO_ID}.mp4"):
        render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output",
               config=make_config())


def test_missing_captions_json_is_an_error(tmp_path, video_dir):
    from clipper.render import RenderError, render

    (video_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    (video_dir / "captions.json").unlink()
    with pytest.raises(RenderError, match="captions.json"):
        render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output",
               config=make_config())


def test_missing_reframe_json_is_an_error(tmp_path, video_dir):
    from clipper.render import RenderError, render

    (video_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    (video_dir / "reframe" / f"{CLIP_ID}.json").unlink()
    with pytest.raises(RenderError, match="entree absente"):
        render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output",
               config=make_config())


def test_missing_subtitles_ass_is_an_error(tmp_path, video_dir):
    from clipper.render import RenderError, render

    (video_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    (video_dir / "subtitles" / f"{CLIP_ID}.ass").unlink()
    with pytest.raises(RenderError, match="sous-titres absents"):
        render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output",
               config=make_config())


def test_clip_id_absent_from_captions_is_an_error(tmp_path, video_dir):
    from clipper.render import RenderError, render

    (video_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    with pytest.raises(RenderError, match="captions.json"):
        render(VIDEO_ID, "99", workspace_dir=video_dir.parent, output_dir=tmp_path / "output",
               config=make_config())


def test_start_end_mismatch_between_captions_and_reframe_is_an_error(tmp_path, video_dir):
    from clipper.render import RenderError, render

    (video_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    reframe = _reframe_json_single_plan()
    reframe["start"] = 9.0
    reframe["end"] = 20.0
    (video_dir / "reframe" / f"{CLIP_ID}.json").write_text(json.dumps(reframe), encoding="utf-8")
    with pytest.raises(RenderError, match="incoherentes"):
        render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output",
               config=make_config())


# --------------------------------------------------------------------------
# Encodeur video : NVENC si CUDA, sinon libx264 (ADR-fb9b)
# --------------------------------------------------------------------------


def test_encoder_selects_nvenc_when_device_is_cuda():
    from clipper.render import CONFIG_DEFAULTS, _encoder

    args = _encoder("cuda", CONFIG_DEFAULTS)
    assert args[:2] == ["-c:v", "h264_nvenc"]


def test_encoder_selects_libx264_when_device_is_cpu():
    from clipper.render import CONFIG_DEFAULTS, _encoder

    args = _encoder("cpu", CONFIG_DEFAULTS)
    assert args[:2] == ["-c:v", "libx264"]


# --------------------------------------------------------------------------
# Construction du filtergraph : accroche 2s, Part N/M, crop/scale, loudnorm
# --------------------------------------------------------------------------


def test_time_expr_is_a_plain_number_for_a_single_rect():
    from clipper.render import _time_expr

    rects = [{"start": 1.0, "end": 3.5, "x": 656, "y": 0, "w": 608, "h": 1080}]
    assert _time_expr(rects, 1.0, "x") == "656"


def test_time_expr_builds_an_if_chain_relative_to_plan_start_for_several_rects():
    from clipper.render import _time_expr

    rects = [
        {"start": 1.0, "end": 1.6, "x": 0, "y": 0, "w": 960, "h": 1080},
        {"start": 1.6, "end": 2.2, "x": 960, "y": 0, "w": 960, "h": 1080},
    ]
    expr = _time_expr(rects, 1.0, "x")
    assert expr == "if(lt(t,0.600000),0,960)"


def test_build_filter_complex_shows_hook_only_during_configured_seconds(tmp_path, video_dir):
    from clipper.render import CONFIG_DEFAULTS, _build_filter_complex

    reframe_data = _reframe_json_single_plan()
    hook_path = tmp_path / "hook.txt"
    hook_path.write_text("Attends de voir ca", encoding="utf-8")
    ass_path = video_dir / "subtitles" / f"{CLIP_ID}.ass"

    filt, _label = _build_filter_complex(
        reframe_data, 1.0, 3.5, ass_path, hook_path, None, tmp_path, CONFIG_DEFAULTS
    )

    assert "drawtext=textfile='hook.txt'" in filt
    assert f"enable='lt(t,{CONFIG_DEFAULTS['hook_seconds']})'" in filt
    assert "part.txt" not in filt


def test_build_filter_complex_includes_part_label_when_multipart(tmp_path, video_dir):
    from clipper.render import CONFIG_DEFAULTS, _build_filter_complex

    reframe_data = _reframe_json_single_plan()
    hook_path = tmp_path / "hook.txt"
    hook_path.write_text("Attends", encoding="utf-8")
    part_path = tmp_path / "part.txt"
    part_path.write_text("Part 2/3", encoding="utf-8")
    ass_path = video_dir / "subtitles" / f"{CLIP_ID}.ass"

    filt, _label = _build_filter_complex(
        reframe_data, 1.0, 3.5, ass_path, hook_path, part_path, tmp_path, CONFIG_DEFAULTS
    )

    assert "drawtext=textfile='part.txt'" in filt


def test_build_filter_complex_normalizes_loudness_to_configured_lufs(tmp_path, video_dir):
    from clipper.render import CONFIG_DEFAULTS, _build_filter_complex

    reframe_data = _reframe_json_single_plan()
    hook_path = tmp_path / "hook.txt"
    hook_path.write_text("x", encoding="utf-8")
    ass_path = video_dir / "subtitles" / f"{CLIP_ID}.ass"

    filt, _label = _build_filter_complex(
        reframe_data, 1.0, 3.5, ass_path, hook_path, None, tmp_path, CONFIG_DEFAULTS
    )

    assert "loudnorm=I=-14.0" in filt


def test_filter_path_is_relative_when_target_and_cwd_share_a_drive(video_dir):
    import os

    from clipper.render import _filter_path

    ass_path = video_dir / "subtitles" / f"{CLIP_ID}.ass"
    scratch = video_dir / "render" / CLIP_ID  # meme arborescence, meme lecteur
    result = _filter_path(ass_path, scratch)
    assert ":" not in result
    assert result == Path(os.path.relpath(ass_path, scratch)).as_posix()


def test_filter_path_escapes_the_drive_colon_when_relpath_is_impossible(tmp_path, monkeypatch):
    from clipper.render import FONTS_DIR, _filter_path

    def _raise(*_args, **_kwargs):
        raise ValueError("cross-device")

    monkeypatch.setattr("clipper.render.os.path.relpath", _raise)
    fonts_result = _filter_path(FONTS_DIR, tmp_path)
    assert fonts_result == FONTS_DIR.resolve().as_posix().replace(":", "\\:")
    assert fonts_result.endswith("clipper/assets/fonts")


def test_build_filter_complex_references_ass_via_fontsdir_option(tmp_path, video_dir):
    from clipper.render import CONFIG_DEFAULTS, _build_filter_complex

    reframe_data = _reframe_json_single_plan()
    hook_path = tmp_path / "hook.txt"
    hook_path.write_text("x", encoding="utf-8")
    ass_path = video_dir / "subtitles" / f"{CLIP_ID}.ass"

    filt, _label = _build_filter_complex(
        reframe_data, 1.0, 3.5, ass_path, hook_path, None, tmp_path, CONFIG_DEFAULTS
    )

    assert "ass=" in filt
    assert "fontsdir=" in filt
    assert "assets/fonts" in filt


def test_panel_filters_applies_boxblur_for_blur_effect(tmp_path):
    from clipper.render import CONFIG_DEFAULTS, _panel_filters

    panel = {
        "name": "background", "effect": "blur", "dest": {"x": 0, "y": 0, "w": OUT_W, "h": OUT_H},
        "rects": [{"start": 1.0, "end": 3.5, "x": 0, "y": 0, "w": SRC_W, "h": SRC_H}],
    }
    lines, _scaled, _dest = _panel_filters(panel, "base", 1.0, "lbl", CONFIG_DEFAULTS)
    assert any("boxblur" in line for line in lines)


def test_panel_filters_has_no_boxblur_without_effect(tmp_path):
    from clipper.render import CONFIG_DEFAULTS, _panel_filters

    panel = {
        "name": "main", "dest": {"x": 0, "y": 0, "w": OUT_W, "h": OUT_H},
        "rects": [{"start": 1.0, "end": 3.5, "x": 656, "y": 0, "w": CROP_W, "h": SRC_H}],
    }
    lines, _scaled, _dest = _panel_filters(panel, "base", 1.0, "lbl", CONFIG_DEFAULTS)
    assert not any("boxblur" in line for line in lines)


def test_panel_filters_downscales_before_boxblur_then_upscales_to_dest(tmp_path):
    """Constat essai reel 2026-09-25 : le boxblur plein cadre est le cout
    dominant du fallback_blur. Le flou est calcule a resolution reduite
    (facteur CONFIG_DEFAULTS['blur_downscale']) puis la sortie est remise a
    la taille de dest, pour un flou beaucoup moins couteux sans changer la
    taille finale du panneau."""
    from clipper.render import CONFIG_DEFAULTS, _panel_filters

    panel = {
        "name": "background", "effect": "blur", "dest": {"x": 0, "y": 0, "w": OUT_W, "h": OUT_H},
        "rects": [{"start": 1.0, "end": 3.5, "x": 0, "y": 0, "w": SRC_W, "h": SRC_H}],
    }
    lines, scaled_label, dest = _panel_filters(panel, "base", 1.0, "lbl", CONFIG_DEFAULTS)

    factor = CONFIG_DEFAULTS["blur_downscale"]
    reduce_idx = next(i for i, line in enumerate(lines) if f"scale=iw/{factor}:ih/{factor}" in line)
    blur_idx = next(i for i, line in enumerate(lines) if "boxblur" in line)
    final_idx = next(i for i, line in enumerate(lines) if f"scale={dest['w']}:{dest['h']}" in line)
    assert reduce_idx < blur_idx < final_idx
    assert scaled_label.endswith("s")


def test_panel_filters_blur_downscale_factor_is_configurable(tmp_path):
    from clipper.render import CONFIG_DEFAULTS, _panel_filters

    panel = {
        "name": "background", "effect": "blur", "dest": {"x": 0, "y": 0, "w": OUT_W, "h": OUT_H},
        "rects": [{"start": 1.0, "end": 3.5, "x": 0, "y": 0, "w": SRC_W, "h": SRC_H}],
    }
    settings = {**CONFIG_DEFAULTS, "blur_downscale": 2}
    lines, _scaled, _dest = _panel_filters(panel, "base", 1.0, "lbl", settings)
    assert any("scale=iw/2:ih/2" in line for line in lines)


def test_plan_filters_splits_source_once_per_panel(tmp_path):
    from clipper.render import CONFIG_DEFAULTS, _plan_filters

    plan = _reframe_json_two_plans()["plans"][0]  # facecam_gameplay : 2 panneaux
    lines, _final = _plan_filters(plan, 0, OUT_W, OUT_H, CONFIG_DEFAULTS)
    assert any(line.startswith("[p0base]split=2") for line in lines)


# --------------------------------------------------------------------------
# Config (ADR-b16b)
# --------------------------------------------------------------------------


def test_config_section_render_resolves_via_clipper_config(tmp_path):
    from clipper.config import load_config

    (tmp_path / "config.toml").write_text("[render]\nmax_fps = 24\n", encoding="utf-8")

    config = load_config(tmp_path / "config.toml")

    section = config.section("render")
    assert section["max_fps"] == 24
    assert section["crf"] == 20


def test_config_defaults_declares_expected_settings():
    from clipper.render import CONFIG_DEFAULTS

    for key in ("max_fps", "crf", "loudnorm_i", "hook_seconds", "blur_radius"):
        assert key in CONFIG_DEFAULTS


# --------------------------------------------------------------------------
# Format letterbox (SPEC-6127, TASK-b7f4) : titre d'ecran sur encadre blanc,
# « Partie N » dessous, pas d'accroche de 2 s, sidecar avec video_rect.
# --------------------------------------------------------------------------

TITLE_ZONE = {"x0": 150, "y0": 160, "x1": 930, "y1": 424}
SUBTITLES_ZONE = {"x0": 150, "y0": 1246, "x1": 930, "y1": 1448}
PART_ZONE = {"x0": 150, "y0": 1464, "x1": 930, "y1": 1520}
VIDEO_RECT = {"x": 0, "y": 440, "w": 1080, "h": 790}


def _reframe_json_letterbox():
    """Plan letterbox tel que l'ecrit reframe (contrat commun SPEC-6127, valeurs
    par defaut pour une source 1920x1080)."""
    panels = [
        _panel("background", 0, 0, SRC_W, SRC_H, {"x": 0, "y": 0, "w": OUT_W, "h": OUT_H}, effect="blur"),
        _panel("main", 222, 0, 1476, SRC_H, dict(VIDEO_RECT)),
    ]
    plan = {
        "index": 0, "start": 1.0, "end": 3.5, "image": None, "llm": None, "layout": "letterbox",
        "reason": None, "faces": [], "panels": panels,
    }
    return {
        "video_id": VIDEO_ID, "clip_id": CLIP_ID, "start": 1.0, "end": 3.5,
        "source": {"width": SRC_W, "height": SRC_H}, "output": {"width": OUT_W, "height": OUT_H},
        "layout": "letterbox", "format": "letterbox",
        "text_zones": {"title": dict(TITLE_ZONE), "subtitles": dict(SUBTITLES_ZONE), "part": dict(PART_ZONE)},
        "plans": [plan],
    }


def _emoji_font_available():
    from clipper.render import CONFIG_DEFAULTS, RenderError, resolve_emoji_font

    try:
        resolve_emoji_font(CONFIG_DEFAULTS)
    except RenderError:
        return False
    return True


no_emoji_font = pytest.mark.skipif(not _emoji_font_available(), reason="police emoji couleur absente")


def _assert_box_inside(box, zone):
    x0, y0, x1, y1 = box
    assert zone["x0"] <= x0 < x1 <= zone["x1"], (box, zone)
    assert zone["y0"] <= y0 < y1 <= zone["y1"], (box, zone)


@pytest.fixture
def letterbox_dir(video_dir):
    (video_dir / "reframe" / f"{CLIP_ID}.json").write_text(json.dumps(_reframe_json_letterbox()), encoding="utf-8")
    return video_dir


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Remplace l'execution de ffmpeg : note la commande et le contenu du
    dossier de travail, ecrit un mp4 factice, pour verifier entrees et sidecar
    sans encoder."""
    calls = []

    def run(cmd, cwd, out_path):
        calls.append({"cmd": list(cmd), "scratch": sorted(p.name for p in Path(cwd).iterdir())})
        Path(out_path).write_bytes(b"mp4")

    monkeypatch.setattr("clipper.render._exec_ffmpeg", run)
    return calls


# --- (1) titre : mise en page mesuree avec la vraie police ---------------------


def test_short_title_fits_on_one_line_centered_at_the_bottom_of_the_title_zone():
    from clipper.render import CONFIG_DEFAULTS, layout_title

    lay = layout_title("Il m'a menti", TITLE_ZONE, CONFIG_DEFAULTS)

    assert lay.lines == ["Il m'a menti"]
    assert lay.font_size == CONFIG_DEFAULTS["title_font_size"]
    _assert_box_inside(lay.box, TITLE_ZONE)
    x0, _y0, x1, y1 = lay.box
    assert y1 == TITLE_ZONE["y1"]
    assert abs((x0 + x1) / 2 - (TITLE_ZONE["x0"] + TITLE_ZONE["x1"]) / 2) <= 1


def test_six_long_words_wrap_on_two_lines_and_the_box_stays_in_the_zone():
    from clipper.render import CONFIG_DEFAULTS, layout_title

    title = "Pourquoi personne ne comprend vraiment cette histoire"
    lay = layout_title(title, TITLE_ZONE, CONFIG_DEFAULTS)

    assert len(lay.lines) == 2
    assert " ".join(lay.lines) == title
    _assert_box_inside(lay.box, TITLE_ZONE)
    assert lay.font_size >= CONFIG_DEFAULTS["title_font_size_min"]


def test_title_that_cannot_fit_at_minimum_size_is_an_explicit_error():
    from clipper.render import CONFIG_DEFAULTS, RenderError, layout_title

    title = " ".join(["Anticonstitutionnellement"] * 6)
    with pytest.raises(RenderError, match="titre"):
        layout_title(title, TITLE_ZONE, CONFIG_DEFAULTS)


def test_title_size_steps_down_until_the_box_fits():
    from clipper.render import CONFIG_DEFAULTS, layout_title

    zone = {"x0": 290, "y0": 160, "x1": 790, "y1": 424}  # 500 px de large
    lay = layout_title("Il m'a menti en garde à vue", zone, CONFIG_DEFAULTS)

    assert lay.font_size < CONFIG_DEFAULTS["title_font_size"]
    _assert_box_inside(lay.box, zone)


def test_title_character_missing_from_poppins_is_an_explicit_error():
    from clipper.render import CONFIG_DEFAULTS, RenderError, layout_title

    with pytest.raises(RenderError, match="Poppins"):
        layout_title("Titre 漢字", TITLE_ZONE, CONFIG_DEFAULTS)


def test_title_is_split_into_text_and_emoji_segments_by_unicode_class():
    from clipper.render import split_segments

    assert split_segments("garde à vue 🚨") == [("text", "garde à vue "), ("emoji", "🚨")]
    assert split_segments("Je t'❤️ fort") == [("text", "Je t'"), ("emoji", "❤️"), ("text", " fort")]
    assert split_segments("Bravo 👍🏽!") == [("text", "Bravo "), ("emoji", "👍🏽"), ("text", "!")]


def test_missing_emoji_font_is_an_explicit_error(tmp_path):
    from clipper.render import CONFIG_DEFAULTS, RenderError, layout_title

    settings = {**CONFIG_DEFAULTS, "emoji_font": str(tmp_path / "absente.ttf")}
    with pytest.raises(RenderError, match="police emoji"):
        layout_title("Il m'a menti 🚨", TITLE_ZONE, settings)


@no_emoji_font
def test_title_png_is_transparent_with_a_colored_emoji_where_the_layout_puts_it(tmp_path):
    from PIL import Image

    from clipper.render import CONFIG_DEFAULTS, title_png

    png = tmp_path / "title.png"
    lay = title_png("Il m'a menti en garde à vue 🚨", TITLE_ZONE, CONFIG_DEFAULTS, png)

    img = Image.open(png)
    assert img.mode == "RGBA"
    assert img.size == (TITLE_ZONE["x1"] - TITLE_ZONE["x0"], TITLE_ZONE["y1"] - TITLE_ZONE["y0"])
    assert img.getpixel((0, 0))[3] == 0  # hors encadre : transparent
    assert len(lay.emoji_boxes) == 1
    _assert_box_inside(lay.emoji_boxes[0], TITLE_ZONE)

    def colored(px):
        r, g, b, a = px
        return a > 200 and max(r, g, b) - min(r, g, b) > 80

    ox, oy = TITLE_ZONE["x0"], TITLE_ZONE["y0"]
    ex0, ey0, ex1, ey1 = (v - o for v, o in zip(lay.emoji_boxes[0], (ox, oy, ox, oy)))
    inside = outside = 0
    for y in range(img.height):
        for x in range(img.width):
            if colored(img.getpixel((x, y))):
                if ex0 <= x < ex1 and ey0 <= y < ey1:
                    inside += 1
                else:
                    outside += 1
    assert inside > 50
    assert outside == 0  # texte noir sur blanc : aucune couleur hors de l'emoji
    # encadre blanc opaque au bord gauche, a mi-hauteur
    bx0, by0, _bx1, by1 = lay.box
    assert img.getpixel((bx0 - ox + 4, (by0 + by1) // 2 - oy)) == (255, 255, 255, 255)


def test_resolve_emoji_font_uses_the_configured_path_when_it_exists(tmp_path):
    from clipper.render import CONFIG_DEFAULTS, resolve_emoji_font

    font = tmp_path / "emoji.ttf"
    font.write_bytes(b"x")
    assert resolve_emoji_font({**CONFIG_DEFAULTS, "emoji_font": str(font)}) == font


# --- filtre ffmpeg en letterbox --------------------------------------------------


def _letterbox_filter(tmp_path, video_dir, part_path=None):
    from clipper.render import CONFIG_DEFAULTS, _build_filter_complex

    ass_path = video_dir / "subtitles" / f"{CLIP_ID}.ass"
    return _build_filter_complex(
        _reframe_json_letterbox(), 1.0, 3.5, ass_path, None, part_path, tmp_path, CONFIG_DEFAULTS,
        title_input=1,
    )


def test_letterbox_filter_overlays_the_title_png_on_the_title_zone_without_hook(tmp_path, video_dir):
    filt, label = _letterbox_filter(tmp_path, video_dir)

    overlay = next(f for f in filt.split(";") if "[1:v]overlay" in f)
    assert f"[1:v]overlay=x={TITLE_ZONE['x0']}:y={TITLE_ZONE['y0']}" in overlay
    assert "enable=" not in overlay  # tout le clip
    assert "drawtext" not in filt  # ni accroche, ni Partie (clip unique)
    assert "lt(t," not in filt
    assert overlay.endswith(f"[{label}]")


def test_letterbox_filter_centers_partie_in_the_part_zone_when_multipart(tmp_path, video_dir):
    part_path = tmp_path / "part.txt"
    part_path.write_text("Partie 2", encoding="utf-8")

    filt, label = _letterbox_filter(tmp_path, video_dir, part_path=part_path)

    part = next(f for f in filt.split(";") if "part.txt" in f)
    assert "drawtext=textfile='part.txt'" in part
    assert f"x={PART_ZONE['x0']}+({PART_ZONE['x1'] - PART_ZONE['x0']}-text_w)/2" in part
    assert "y_align=baseline" in part
    assert "enable=" not in part  # tout le clip
    assert filt.index("[1:v]overlay") < filt.index("part.txt")
    assert part.endswith(f"[{label}]")
    assert sum("drawtext" in f for f in filt.split(";")) == 1  # pas d'accroche


# --- render en letterbox : entrees, sidecar ------------------------------------


def test_letterbox_render_passes_the_title_png_as_second_input_and_writes_video_rect(
    tmp_path, letterbox_dir, fake_ffmpeg, cpu_device
):
    from clipper.render import render

    (letterbox_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    render(VIDEO_ID, CLIP_ID, workspace_dir=letterbox_dir.parent, output_dir=tmp_path / "output",
           config=make_config())

    cmd = fake_ffmpeg[0]["cmd"]
    inputs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]
    assert len(inputs) == 2
    assert inputs[1].endswith("title.png")
    assert "title.png" in fake_ffmpeg[0]["scratch"]
    assert "hook.txt" not in fake_ffmpeg[0]["scratch"]
    assert "part.txt" not in fake_ffmpeg[0]["scratch"]

    data = json.loads((tmp_path / "output" / VIDEO_ID / f"{CLIP_ID}.json").read_text(encoding="utf-8"))
    assert data["layout"] == "letterbox"
    assert data["video_rect"] == VIDEO_RECT
    assert data["screen_title"] == "Il m'a menti en garde à vue"


def test_letterbox_render_writes_partie_n_when_multipart(tmp_path, letterbox_dir, fake_ffmpeg, cpu_device):
    from clipper.render import render

    (letterbox_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    (letterbox_dir / "captions.json").write_text(
        json.dumps(_captions_json(part=2, parts_total=3)), encoding="utf-8")

    render(VIDEO_ID, CLIP_ID, workspace_dir=letterbox_dir.parent, output_dir=tmp_path / "output",
           config=make_config())

    assert "part.txt" in fake_ffmpeg[0]["scratch"]
    filt = fake_ffmpeg[0]["cmd"][fake_ffmpeg[0]["cmd"].index("-filter_complex") + 1]
    assert "drawtext=textfile='part.txt'" in filt


def test_letterbox_partie_text_is_partie_n(tmp_path, letterbox_dir, monkeypatch, cpu_device):
    from clipper.render import render

    (letterbox_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    (letterbox_dir / "captions.json").write_text(
        json.dumps(_captions_json(part=2, parts_total=3)), encoding="utf-8")
    seen = []

    def run(cmd, cwd, out_path):
        seen.append((Path(cwd) / "part.txt").read_text(encoding="utf-8"))
        Path(out_path).write_bytes(b"mp4")

    monkeypatch.setattr("clipper.render._exec_ffmpeg", run)
    render(VIDEO_ID, CLIP_ID, workspace_dir=letterbox_dir.parent, output_dir=tmp_path / "output",
           config=make_config())

    assert seen == ["Partie 2"]


def test_letterbox_partie_too_big_for_its_zone_is_an_explicit_error(tmp_path, letterbox_dir, fake_ffmpeg, cpu_device):
    from clipper.render import RenderError, render

    (letterbox_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    (letterbox_dir / "captions.json").write_text(
        json.dumps(_captions_json(part=2, parts_total=3)), encoding="utf-8")
    with pytest.raises(RenderError, match="Partie"):
        render(VIDEO_ID, CLIP_ID, workspace_dir=letterbox_dir.parent, output_dir=tmp_path / "output",
               config=make_config(part_font_size=120))
    assert fake_ffmpeg == []


def test_letterbox_without_text_zones_asks_to_rerun_reframe(tmp_path, letterbox_dir, fake_ffmpeg):
    from clipper.render import RenderError, render

    (letterbox_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    reframe = _reframe_json_letterbox()
    del reframe["text_zones"]
    (letterbox_dir / "reframe" / f"{CLIP_ID}.json").write_text(json.dumps(reframe), encoding="utf-8")
    with pytest.raises(RenderError, match="reframe"):
        render(VIDEO_ID, CLIP_ID, workspace_dir=letterbox_dir.parent, output_dir=tmp_path / "output",
               config=make_config())
    assert fake_ffmpeg == []


@pytest.mark.parametrize("fixture", ["video_dir", "letterbox_dir"])
def test_missing_screen_title_asks_to_rerun_captions_force(tmp_path, fixture, request, fake_ffmpeg):
    from clipper.render import RenderError, render

    d = request.getfixturevalue(fixture)
    (d / f"{VIDEO_ID}.mp4").write_bytes(b"")
    captions = _captions_json()
    del captions["clips"][0]["screen_title"]
    (d / "captions.json").write_text(json.dumps(captions), encoding="utf-8")
    with pytest.raises(RenderError, match="captions --force"):
        render(VIDEO_ID, CLIP_ID, workspace_dir=d.parent, output_dir=tmp_path / "output", config=make_config())
    assert fake_ffmpeg == []


def test_crop_sidecar_also_carries_screen_title(tmp_path, video_dir, fake_ffmpeg, cpu_device):
    from clipper.render import render

    (video_dir / f"{VIDEO_ID}.mp4").write_bytes(b"")
    render(VIDEO_ID, CLIP_ID, workspace_dir=video_dir.parent, output_dir=tmp_path / "output", config=make_config())

    data = json.loads((tmp_path / "output" / VIDEO_ID / f"{CLIP_ID}.json").read_text(encoding="utf-8"))
    assert data["screen_title"] == "Il m'a menti en garde à vue"
    assert data["layout"] == "single"
    assert "video_rect" not in data
    cmd = fake_ffmpeg[0]["cmd"]
    assert cmd.count("-i") == 1  # hors letterbox : rendu inchange, pas de PNG de titre
    assert "hook.txt" in fake_ffmpeg[0]["scratch"]


# --- rendu ffmpeg reel d'un plan letterbox synthetique ---------------------------


@no_ffmpeg
@no_ffprobe
def test_render_letterbox_real_ffmpeg_draws_the_white_title_box_and_partie(
    tmp_path, letterbox_dir, synthetic_source, cpu_device
):
    from PIL import Image

    from clipper.render import CONFIG_DEFAULTS, layout_title, render

    (letterbox_dir / "captions.json").write_text(
        json.dumps(_captions_json(part=1, parts_total=2)), encoding="utf-8")
    out = render(VIDEO_ID, CLIP_ID, workspace_dir=letterbox_dir.parent, output_dir=tmp_path / "output",
                 config=make_config(x264_preset="ultrafast"))

    probe = _ffprobe_json(out)
    streams = {s["codec_type"]: s for s in probe["streams"]}
    assert (streams["video"]["width"], streams["video"]["height"]) == (OUT_W, OUT_H)
    assert float(probe["format"]["duration"]) == pytest.approx(2.5, abs=0.1)

    lay = layout_title("Il m'a menti en garde à vue", TITLE_ZONE, CONFIG_DEFAULTS)
    bx0, by0, _bx1, by1 = lay.box
    for t in (0.2, 2.3):  # debut et fin du clip : titre et Partie tout du long
        frame = tmp_path / f"frame_{t}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(out),
                        "-frames:v", "1", str(frame)], check=True)
        img = Image.open(frame).convert("RGB")
        r, g, b = img.getpixel((bx0 + 6, (by0 + by1) // 2))
        assert min(r, g, b) > 225, (t, (r, g, b))  # bord de l'encadre blanc
        # Partie : du blanc (texte) dans la zone part
        white = sum(
            1 for y in range(PART_ZONE["y0"], PART_ZONE["y1"]) for x in range(PART_ZONE["x0"], PART_ZONE["x1"], 2)
            if min(img.getpixel((x, y))) > 235
        )
        assert white > 30, t
