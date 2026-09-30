from __future__ import annotations

import json
import subprocess
import threading
import time
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


def _write_transcript(workspace_dir: Path, video_id: str, segments: list[dict]) -> None:
    video_dir = workspace_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "transcript.json").write_text(
        json.dumps({"segments": segments}), encoding="utf-8"
    )


def _write_audio(workspace_dir: Path, video_id: str, peaks: list[dict]) -> None:
    video_dir = workspace_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "audio.json").write_text(json.dumps({"peaks": peaks}), encoding="utf-8")


def _full_speech(workspace_dir: Path, video_id: str = "vid1") -> None:
    """Transcript covering the whole video (end far past any real duration:
    ffmpeg just stops at EOF) -- the decode range every test below had
    before TASK-22a9 restricted it to speech."""
    _write_transcript(workspace_dir, video_id, [{"start": 0.0, "end": 1e6}])


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
    _full_speech(workspace_dir)
    result = detect_scenes(three_scene_video, workspace_dir, "vid1")

    assert len(result["scenes"]) == 3


def test_detect_scenes_writes_scenes_json_with_start_end(isolated_cwd, three_scene_video):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
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
    _full_speech(workspace_dir)
    result = detect_scenes(
        three_scene_video, workspace_dir, "vid1", keyframe_interval_seconds=100.0
    )

    assert len(result["frames"]) == len(result["scenes"]) == 3


def test_detect_scenes_writes_jpeg_frames_under_frames_dir(isolated_cwd, three_scene_video):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
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
    _full_speech(workspace_dir)
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

    # scenes.json existe deja : transcript.json n'est pas lu, pas besoin ici.
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
    _full_speech(workspace_dir)

    result = detect_scenes(three_scene_video, workspace_dir, "vid1", force=True)

    assert len(result["scenes"]) == 3


# -- TASK-1f16 : analyse reduite, keyframes pleine resolution, decodeur strict --


@pytest.fixture
def hd_three_scene_video(tmp_path):
    """640x360 at 50 fps: wider than the analysis width and faster than the
    analysis frame rate bound used below, cuts at 2 s and 4 s."""
    video_path = tmp_path / "hd_three_scenes.mp4"
    _make_color_video(
        video_path, ["red", "blue", "green"], segment_seconds=2.0, size="640x360", fps=50
    )
    return video_path


@pytest.fixture
def recorded_analysis_frames(monkeypatch):
    """Record the shape of every frame handed to the content detector."""
    import clipper.scenes as scenes_module

    shapes: list[tuple[int, ...]] = []
    real_detector = scenes_module.ContentDetector

    class RecordingDetector(real_detector):
        def process_frame(self, timecode, frame_img):
            shapes.append(frame_img.shape)
            return super().process_frame(timecode, frame_img)

    monkeypatch.setattr(scenes_module, "ContentDetector", RecordingDetector)
    return shapes


@pytest.fixture
def recorded_ffmpeg_commands(monkeypatch):
    """Record every ffmpeg command used to decode analysis frames (the real
    process still runs -- only the command line is captured)."""
    import clipper.scenes as scenes_module

    commands: list[list[str]] = []
    real_popen = subprocess.Popen

    def recording_popen(cmd, *args, **kwargs):
        commands.append(cmd)
        return real_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(scenes_module.subprocess, "Popen", recording_popen)
    return commands


def test_config_defaults_declares_reduced_decoding_options():
    from clipper.scenes import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["analysis_width"] == 256
    assert CONFIG_DEFAULTS["analysis_max_fps"] == 30.0
    assert CONFIG_DEFAULTS["decoder"] == ""


def test_detect_scenes_accepts_every_config_default_as_keyword(isolated_cwd, three_scene_video):
    """clipper.pipeline passes the whole [scenes] section as keywords."""
    from clipper.scenes import CONFIG_DEFAULTS, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    result = detect_scenes(three_scene_video, workspace_dir, "vid1", **CONFIG_DEFAULTS)

    assert len(result["scenes"]) == 3


def test_detection_analyses_frames_at_reduced_width(
    isolated_cwd, hd_three_scene_video, recorded_analysis_frames
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    detect_scenes(
        hd_three_scene_video, workspace_dir, "vid1",
        analysis_width=160, analysis_max_fps=50.0,
    )

    assert recorded_analysis_frames
    assert {shape[:2] for shape in recorded_analysis_frames} == {(90, 160)}


def test_detection_analyses_at_most_analysis_max_fps(
    isolated_cwd, hd_three_scene_video, recorded_analysis_frames
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    detect_scenes(
        hd_three_scene_video, workspace_dir, "vid1", analysis_max_fps=10.0
    )

    # 6 s de video a 50 fps, analysee a 10 fps -> ~60 images (300 a pleine cadence)
    assert 55 <= len(recorded_analysis_frames) <= 65


def test_cuts_stay_within_half_a_second_with_reduced_analysis(isolated_cwd, hd_three_scene_video):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    result = detect_scenes(
        hd_three_scene_video, workspace_dir, "vid1",
        analysis_width=128, analysis_max_fps=10.0,
    )

    starts = [scene["start"] for scene in result["scenes"]]
    assert len(starts) == 3
    assert starts[0] == pytest.approx(0.0, abs=0.5)
    assert starts[1] == pytest.approx(2.0, abs=0.5)
    assert starts[2] == pytest.approx(4.0, abs=0.5)
    assert result["scenes"][-1]["end"] == pytest.approx(6.0, abs=0.5)


def test_keyframes_are_extracted_at_full_resolution(isolated_cwd, hd_three_scene_video):
    import cv2

    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    result = detect_scenes(
        hd_three_scene_video, workspace_dir, "vid1",
        analysis_width=160, keyframe_interval_seconds=100.0,
    )

    assert len(result["frames"]) == 3
    for frame in result["frames"]:
        image = cv2.imread(str(workspace_dir / "vid1" / frame["path"]))
        assert image.shape[:2] == (360, 640)


def test_keyframes_show_the_image_at_their_timecode(isolated_cwd, hd_three_scene_video):
    """Scene 0 is red, 1 blue, 2 green: the keyframe of each scene is taken
    at its middle and must show that scene's colour (BGR)."""
    import cv2

    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    result = detect_scenes(
        hd_three_scene_video, workspace_dir, "vid1", keyframe_interval_seconds=100.0
    )

    dominant = []
    for frame in result["frames"]:
        image = cv2.imread(str(workspace_dir / "vid1" / frame["path"]))
        dominant.append(int(image.reshape(-1, 3).mean(axis=0).argmax()))
    assert dominant == [2, 0, 1]


def test_scenes_json_keeps_its_format(isolated_cwd, three_scene_video):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    detect_scenes(three_scene_video, workspace_dir, "vid1")

    on_disk = json.loads((workspace_dir / "vid1" / "scenes.json").read_text(encoding="utf-8"))
    assert set(on_disk) == {"scenes", "frames"}
    for scene in on_disk["scenes"]:
        assert set(scene) == {"start", "end"}
        assert isinstance(scene["start"], float) and isinstance(scene["end"], float)
    for frame in on_disk["frames"]:
        assert set(frame) == {"path", "timecode", "scene"}
        assert isinstance(frame["timecode"], float) and isinstance(frame["scene"], int)


def test_configured_decoder_is_used(isolated_cwd, three_scene_video):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    result = detect_scenes(three_scene_video, workspace_dir, "vid1", decoder="h264")

    assert len(result["scenes"]) == 3


def test_unknown_decoder_fails_the_step_without_falling_back(isolated_cwd, three_scene_video):
    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    with pytest.raises(ScenesError, match="decodeur_inexistant"):
        detect_scenes(three_scene_video, workspace_dir, "vid1", decoder="decodeur_inexistant")

    assert not (workspace_dir / "vid1" / "scenes.json").exists()


def test_decoder_unable_to_decode_the_stream_fails_the_step(isolated_cwd, three_scene_video):
    """A decoder that exists but does not match the stream (vp9 on h264)
    is a failure, never a silent switch to another decoder."""
    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    with pytest.raises(ScenesError, match="vp9"):
        detect_scenes(three_scene_video, workspace_dir, "vid1", decoder="vp9")

    assert not (workspace_dir / "vid1" / "scenes.json").exists()


def test_missing_ffmpeg_fails_the_step_with_a_clear_message(isolated_cwd, three_scene_video):
    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    with pytest.raises(ScenesError, match="introuvable"):
        detect_scenes(
            three_scene_video, workspace_dir, "vid1",
            ffmpeg_bin="ffmpeg-absent-du-path",
        )


# -- TASK-559adc7a1505 : extraction des images cles en parallele --


def _decode_commands(commands: list[list[str]]) -> list[list[str]]:
    """``recorded_ffmpeg_commands`` also sees ffprobe and keyframe-extraction
    calls (subprocess.run uses the same patched Popen internally): keep only
    the raw-video decode passes used for scene detection."""
    return [cmd for cmd in commands if "rawvideo" in cmd]


def _has_overlap(intervals: list[tuple[float, float]]) -> bool:
    ordered = sorted(intervals)
    return any(ordered[i][1] > ordered[i + 1][0] for i in range(len(ordered) - 1))


@pytest.fixture
def recorded_extraction_intervals(monkeypatch):
    """Record start/end wall-clock time of every _extract_frame call, and
    return a fake image so no real ffmpeg extraction runs."""
    import numpy as np

    import clipper.scenes as scenes_module

    intervals: list[tuple[float, float]] = []
    lock = threading.Lock()

    def fake_extract_frame(video_path, timecode, decoder, ffmpeg_bin):
        start = time.monotonic()
        time.sleep(0.05)
        end = time.monotonic()
        with lock:
            intervals.append((start, end))
        return np.zeros((4, 4, 3), dtype=np.uint8)

    monkeypatch.setattr(scenes_module, "_extract_frame", fake_extract_frame)
    return intervals


def test_config_defaults_declares_extract_parallel():
    from clipper.scenes import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["extract_parallel"] == 4


def test_extract_parallel_below_one_is_refused(isolated_cwd, three_scene_video):
    from clipper.scenes import ScenesError, detect_scenes

    with pytest.raises(ScenesError, match="extract_parallel"):
        detect_scenes(
            three_scene_video, isolated_cwd / "workspace", "vid1", extract_parallel=0
        )


def test_extraction_runs_in_parallel_up_to_extract_parallel(
    isolated_cwd, three_scene_video, recorded_extraction_intervals
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    detect_scenes(
        three_scene_video, workspace_dir, "vid1",
        keyframe_interval_seconds=100.0, extract_parallel=4,
    )

    assert _has_overlap(recorded_extraction_intervals)


def test_extraction_is_sequential_when_extract_parallel_is_one(
    isolated_cwd, three_scene_video, recorded_extraction_intervals
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    detect_scenes(
        three_scene_video, workspace_dir, "vid1",
        keyframe_interval_seconds=100.0, extract_parallel=1,
    )

    assert not _has_overlap(recorded_extraction_intervals)


def test_scenes_json_identical_between_sequential_and_parallel_extraction(
    isolated_cwd, three_scene_video, monkeypatch
):
    """Meme sortie (timecodes, noms de fichiers, ordre, octets JPEG) que les
    extractions se terminent dans l'ordre (extract_parallel=1) ou non
    (extract_parallel=4, delais inverses pour forcer un ordre d'arrivee
    different de l'ordre de soumission)."""
    import numpy as np

    import clipper.scenes as scenes_module

    def fake_extract_frame(video_path, timecode, decoder, ffmpeg_bin):
        time.sleep(max(0.0, 0.06 - timecode * 0.001))
        seed = int(timecode * 1000) % 256
        return np.full((4, 4, 3), seed, dtype=np.uint8)

    monkeypatch.setattr(scenes_module, "_extract_frame", fake_extract_frame)

    from clipper.scenes import detect_scenes

    workspace_seq = isolated_cwd / "workspace_seq"
    _full_speech(workspace_seq)
    result_seq = detect_scenes(
        three_scene_video, workspace_seq, "vid1",
        keyframe_interval_seconds=100.0, extract_parallel=1,
    )

    workspace_par = isolated_cwd / "workspace_par"
    _full_speech(workspace_par)
    result_par = detect_scenes(
        three_scene_video, workspace_par, "vid1",
        keyframe_interval_seconds=100.0, extract_parallel=4,
    )

    assert result_seq["scenes"] == result_par["scenes"]
    assert [f["path"] for f in result_seq["frames"]] == [f["path"] for f in result_par["frames"]]
    assert [f["timecode"] for f in result_seq["frames"]] == [
        f["timecode"] for f in result_par["frames"]
    ]
    assert [f["scene"] for f in result_seq["frames"]] == [f["scene"] for f in result_par["frames"]]

    for f_seq, f_par in zip(result_seq["frames"], result_par["frames"]):
        bytes_seq = (workspace_seq / "vid1" / f_seq["path"]).read_bytes()
        bytes_par = (workspace_par / "vid1" / f_par["path"]).read_bytes()
        assert bytes_seq == bytes_par


def test_extraction_failure_propagates_and_does_not_write_scenes_json_when_parallel(
    isolated_cwd, three_scene_video, monkeypatch
):
    import clipper.scenes as scenes_module

    def failing_extract_frame(video_path, timecode, decoder, ffmpeg_bin):
        raise scenes_module.ScenesError(f"echec simule a {timecode:.3f}s")

    monkeypatch.setattr(scenes_module, "_extract_frame", failing_extract_frame)

    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    with pytest.raises(ScenesError, match=r"\d+\.\d+s"):
        detect_scenes(
            three_scene_video, workspace_dir, "vid1",
            keyframe_interval_seconds=100.0, extract_parallel=4,
        )

    assert not (workspace_dir / "vid1" / "scenes.json").exists()


# -- TASK-22a9 : ne decoder que les zones de parole (VAD de la transcription) --


def test_config_defaults_declares_speech_margin_seconds():
    from clipper.scenes import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["speech_margin_seconds"] == 5.0


def test_detect_scenes_requires_transcript_json(isolated_cwd, three_scene_video):
    """transcript.json est une entree obligatoire, comme scenes.json pour
    clipper.reframe : absent, l'etape echoue plutot que de decoder toute la
    video en silence (ADR-ad2e)."""
    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    with pytest.raises(ScenesError, match="transcript.json"):
        detect_scenes(three_scene_video, workspace_dir, "vid1")

    assert not (workspace_dir / "vid1" / "scenes.json").exists()


def test_detect_scenes_fails_when_transcript_has_no_speech_segment(
    isolated_cwd, three_scene_video
):
    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [])

    with pytest.raises(ScenesError, match="aucun segment de parole"):
        detect_scenes(three_scene_video, workspace_dir, "vid1")

    assert not (workspace_dir / "vid1" / "scenes.json").exists()


def test_detect_scenes_only_decodes_the_speech_windows(
    isolated_cwd, three_scene_video, recorded_ffmpeg_commands, recorded_analysis_frames
):
    """three_scene_video dure 6 s (25 fps -> 150 images a pleine cadence) ;
    deux plages de parole de 0,5 s a chaque bout, marge 0,5 s, ne couvrent
    que 2 s : largement moins d'images analysees que la video entiere."""
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(
        workspace_dir, "vid1",
        [{"start": 0.0, "end": 0.5}, {"start": 5.5, "end": 6.0}],
    )

    detect_scenes(three_scene_video, workspace_dir, "vid1", speech_margin_seconds=0.5)

    decode_commands = _decode_commands(recorded_ffmpeg_commands)
    ss_values = sorted(float(cmd[cmd.index("-ss") + 1]) for cmd in decode_commands)
    assert ss_values == pytest.approx([0.0, 5.0])
    assert len(recorded_analysis_frames) < 100


def test_detect_scenes_merges_speech_windows_that_overlap_once_widened(
    isolated_cwd, three_scene_video, recorded_ffmpeg_commands
):
    """Deux lignes a [0,1] et [2,3] separees d'1 s : une marge de 1 s les
    elargit a [0,2] et [1,4], qui se chevauchent et fusionnent en une seule
    fenetre [0,4] (un seul appel ffmpeg, pas deux)."""
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(
        workspace_dir, "vid1",
        [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}],
    )

    detect_scenes(three_scene_video, workspace_dir, "vid1", speech_margin_seconds=1.0)

    decode_commands = _decode_commands(recorded_ffmpeg_commands)
    assert len(decode_commands) == 1
    cmd = decode_commands[0]
    assert float(cmd[cmd.index("-ss") + 1]) == pytest.approx(0.0)
    assert float(cmd[cmd.index("-t") + 1]) == pytest.approx(4.0)


def test_detect_scenes_adds_a_window_around_an_audio_peak_when_audio_json_exists(
    isolated_cwd, three_scene_video, recorded_ffmpeg_commands
):
    """audio.json n'existe normalement pas encore quand scenes tourne
    (clipper.pipeline.STEPS l'enchaine apres) ; s'il existe deja (rejeu avec
    --force), ses pics hors parole deviennent eux aussi des fenetres."""
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [{"start": 0.0, "end": 0.5}])
    _write_audio(workspace_dir, "vid1", [{"timecode": 5.5, "relative_db": 12.0}])

    detect_scenes(three_scene_video, workspace_dir, "vid1", speech_margin_seconds=0.5)

    decode_commands = _decode_commands(recorded_ffmpeg_commands)
    ss_values = sorted(float(cmd[cmd.index("-ss") + 1]) for cmd in decode_commands)
    assert ss_values == pytest.approx([0.0, 5.0])


def test_detect_scenes_ignores_audio_json_when_absent(
    isolated_cwd, three_scene_video, recorded_ffmpeg_commands
):
    """audio.json absent (le cas normal) : pas d'erreur, seule la parole
    borne le decodage."""
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [{"start": 0.0, "end": 0.5}])

    detect_scenes(three_scene_video, workspace_dir, "vid1", speech_margin_seconds=0.5)

    assert len(_decode_commands(recorded_ffmpeg_commands)) == 1


def test_speech_margin_seconds_widens_each_window(
    isolated_cwd, three_scene_video, recorded_ffmpeg_commands
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [{"start": 2.0, "end": 3.0}])

    detect_scenes(three_scene_video, workspace_dir, "vid1", speech_margin_seconds=0.0)

    decode_commands = _decode_commands(recorded_ffmpeg_commands)
    assert len(decode_commands) == 1
    cmd = decode_commands[0]
    assert float(cmd[cmd.index("-ss") + 1]) == pytest.approx(2.0)
    assert float(cmd[cmd.index("-t") + 1]) == pytest.approx(1.0)


def test_speech_window_start_never_goes_below_zero(
    isolated_cwd, three_scene_video, recorded_ffmpeg_commands
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [{"start": 0.2, "end": 0.5}])

    detect_scenes(three_scene_video, workspace_dir, "vid1", speech_margin_seconds=5.0)

    cmd = _decode_commands(recorded_ffmpeg_commands)[0]
    assert float(cmd[cmd.index("-ss") + 1]) == pytest.approx(0.0)


def test_unanalysed_ranges_produce_no_scene_entries(isolated_cwd, three_scene_video):
    """Video de 3 plans (coupures a 2 s et 4 s) mais parole seulement dans
    [0, 0.5] (+- marge) : la fenetre decodee ne recouvre aucune coupure, donc
    scenes.json garde un seul plan (format inchange, la plage non analysee
    n'a simplement pas de coupure)."""
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [{"start": 0.0, "end": 0.5}])

    result = detect_scenes(three_scene_video, workspace_dir, "vid1", speech_margin_seconds=0.5)

    assert len(result["scenes"]) == 1
    assert result["scenes"][0]["end"] <= 1.0 + 1e-3
    assert set(result) == {"scenes", "frames"}


def test_cut_inside_a_speech_window_is_detected_like_a_full_decode(
    isolated_cwd, hd_three_scene_video
):
    """La coupure a 2 s (rouge -> bleu) tombe au milieu d'une fenetre de
    parole [0.5, 3.5] : elle est detectee au meme instant qu'un decodage
    entier (test_cuts_stay_within_half_a_second_with_reduced_analysis)."""
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [{"start": 1.5, "end": 2.5}])

    result = detect_scenes(
        hd_three_scene_video, workspace_dir, "vid1",
        analysis_width=128, analysis_max_fps=10.0, speech_margin_seconds=1.0,
    )

    starts = [scene["start"] for scene in result["scenes"]]
    assert any(abs(start - 2.0) < 0.5 for start in starts)


def test_cuts_match_a_full_decode_when_speech_covers_the_whole_video(
    isolated_cwd, hd_three_scene_video
):
    """Une seule fenetre de parole couvrant toute la video (marge 0) doit
    retrouver exactement les coupures d'un decodage entier."""
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [{"start": 0.0, "end": 6.0}])

    result = detect_scenes(
        hd_three_scene_video, workspace_dir, "vid1",
        analysis_width=128, analysis_max_fps=10.0, speech_margin_seconds=0.0,
    )

    starts = [scene["start"] for scene in result["scenes"]]
    assert len(starts) == 3
    assert starts[0] == pytest.approx(0.0, abs=0.5)
    assert starts[1] == pytest.approx(2.0, abs=0.5)
    assert starts[2] == pytest.approx(4.0, abs=0.5)
    assert result["scenes"][-1]["end"] == pytest.approx(6.0, abs=0.5)
