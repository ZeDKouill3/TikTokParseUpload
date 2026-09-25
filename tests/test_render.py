from __future__ import annotations

import json
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
