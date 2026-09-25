from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def _make_color_video(
    path: Path,
    colors: list[str],
    segment_seconds: float,
    size: str = "320x240",
    fps: int = 25,
) -> None:
    """Build a video out of solid-color segments concatenated together, so
    each cut between colors is an unambiguous scene change for PySceneDetect
    (see TASK-e374's done_criteria: synthetic video via ffmpeg, color flats
    that change)."""
    inputs: list[str] = []
    for color in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={color}:s={size}:d={segment_seconds}"]
    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        f"concat=n={len(colors)}:v=1:a=0",
        "-r",
        str(fps),
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.fixture
def three_scene_video(tmp_path):
    video_path = tmp_path / "three_scenes.mp4"
    _make_color_video(video_path, ["red", "blue", "green"], segment_seconds=2.0)
    return video_path


@pytest.fixture
def one_scene_video(tmp_path):
    video_path = tmp_path / "one_scene.mp4"
    _make_color_video(video_path, ["red"], segment_seconds=12.0)
    return video_path


def test_config_defaults_declares_scene_detection_options():
    from clipper.scenes import CONFIG_DEFAULTS

    assert "threshold" in CONFIG_DEFAULTS
    assert "keyframe_interval_seconds" in CONFIG_DEFAULTS


def test_config_section_scenes_resolves_via_clipper_config(isolated_cwd):
    from clipper.config import load_config

    (isolated_cwd / "config.toml").write_text(
        "[scenes]\nthreshold = 30.0\n", encoding="utf-8"
    )

    config = load_config(isolated_cwd / "config.toml")

    assert config.section("scenes")["threshold"] == 30.0


def test_detect_scenes_finds_correct_number_of_cuts(isolated_cwd, three_scene_video):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    result = detect_scenes(three_scene_video, workspace_dir, "vid1")

    assert len(result["scenes"]) == 3


def test_detect_scenes_writes_scenes_json_with_start_end(isolated_cwd, three_scene_video):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    result = detect_scenes(three_scene_video, workspace_dir, "vid1")

    scenes_file = workspace_dir / "vid1" / "scenes.json"
    on_disk = json.loads(scenes_file.read_text(encoding="utf-8"))
    assert on_disk == result

    for scene in result["scenes"]:
        assert set(scene) == {"start", "end"}
        assert scene["end"] > scene["start"]


def test_detect_scenes_extracts_one_keyframe_per_scene(isolated_cwd, three_scene_video):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    result = detect_scenes(
        three_scene_video, workspace_dir, "vid1", keyframe_interval_seconds=100.0
    )

    assert len(result["frames"]) == len(result["scenes"]) == 3


def test_detect_scenes_writes_jpeg_frames_under_frames_dir(isolated_cwd, three_scene_video):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    result = detect_scenes(
        three_scene_video, workspace_dir, "vid1", keyframe_interval_seconds=100.0
    )

    frames_dir = workspace_dir / "vid1" / "frames"
    assert result["frames"]
    for frame in result["frames"]:
        frame_path = workspace_dir / "vid1" / frame["path"]
        assert frame_path.exists()
        assert frame_path.suffix == ".jpg"
        assert frame_path.parent == frames_dir
        assert "timecode" in frame


def test_detect_scenes_adds_extra_keyframes_every_n_seconds_in_long_scenes(
    isolated_cwd, one_scene_video
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    result = detect_scenes(
        one_scene_video, workspace_dir, "vid1", keyframe_interval_seconds=5.0
    )

    assert len(result["scenes"]) == 1
    scene_frames = [f for f in result["frames"] if f["scene"] == 0]
    # duree ~12s, intervalle 5s -> image cle + images a 5s et 10s = 3
    assert len(scene_frames) == 3


def test_detect_scenes_skips_recompute_when_scenes_json_already_exists(
    isolated_cwd, three_scene_video
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    video_dir = workspace_dir / "vid1"
    video_dir.mkdir(parents=True)
    existing = {"scenes": [{"start": 0.0, "end": 1.0}], "frames": []}
    (video_dir / "scenes.json").write_text(json.dumps(existing), encoding="utf-8")

    result = detect_scenes(three_scene_video, workspace_dir, "vid1")

    assert result == existing


def test_detect_scenes_force_recomputes_even_if_scenes_json_exists(
    isolated_cwd, three_scene_video
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    video_dir = workspace_dir / "vid1"
    video_dir.mkdir(parents=True)
    (video_dir / "scenes.json").write_text(
        json.dumps({"scenes": [{"start": 0.0, "end": 1.0}], "frames": []}),
        encoding="utf-8",
    )

    result = detect_scenes(three_scene_video, workspace_dir, "vid1", force=True)

    assert len(result["scenes"]) == 3
