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

    def fake_extract_frame(video_path, timecode, decoder, ffmpeg_bin, threads=0):
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
        keyframe_interval_seconds=100.0, extract_parallel=4, extract_batch=1,
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
        keyframe_interval_seconds=100.0, extract_parallel=1, extract_batch=1,
    )

    assert not _has_overlap(recorded_extraction_intervals)


def test_scenes_json_identical_between_sequential_and_parallel_extraction(
    isolated_cwd, three_scene_video, monkeypatch
):
    """Meme sortie (timecodes, noms de fichiers, ordre, octets JPEG) que les
    extractions se terminent dans l'ordre (extract_parallel=1, extract_batch=1) ou non
    (extract_parallel=4, extract_batch=1, delais inverses pour forcer un ordre d'arrivee
    different de l'ordre de soumission)."""
    import numpy as np

    import clipper.scenes as scenes_module

    def fake_extract_frame(video_path, timecode, decoder, ffmpeg_bin, threads=0):
        time.sleep(max(0.0, 0.06 - timecode * 0.001))
        seed = int(timecode * 1000) % 256
        return np.full((4, 4, 3), seed, dtype=np.uint8)

    monkeypatch.setattr(scenes_module, "_extract_frame", fake_extract_frame)

    from clipper.scenes import detect_scenes

    workspace_seq = isolated_cwd / "workspace_seq"
    _full_speech(workspace_seq)
    result_seq = detect_scenes(
        three_scene_video, workspace_seq, "vid1",
        keyframe_interval_seconds=100.0, extract_parallel=1, extract_batch=1,
    )

    workspace_par = isolated_cwd / "workspace_par"
    _full_speech(workspace_par)
    result_par = detect_scenes(
        three_scene_video, workspace_par, "vid1",
        keyframe_interval_seconds=100.0, extract_parallel=4, extract_batch=1,
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

    def failing_extract_frame(video_path, timecode, decoder, ffmpeg_bin, threads=0):
        raise scenes_module.ScenesError(f"echec simule a {timecode:.3f}s")

    monkeypatch.setattr(scenes_module, "_extract_frame", failing_extract_frame)

    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _full_speech(workspace_dir)
    with pytest.raises(ScenesError, match=r"\d+\.\d+s"):
        detect_scenes(
            three_scene_video, workspace_dir, "vid1",
            keyframe_interval_seconds=100.0, extract_parallel=4, extract_batch=1,
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


def test_detect_scenes_widens_windows_around_an_audio_peak_with_peak_windows(
    isolated_cwd, three_scene_video, recorded_ffmpeg_commands
):
    """SPEC-b0f3 R4bis : avec peak_windows=True, les pics hors parole
    d'audio.json (qui tourne avant scenes) deviennent eux aussi des fenetres."""
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [{"start": 0.0, "end": 0.5}])
    _write_audio(workspace_dir, "vid1", [{"timecode": 5.5, "relative_db": 12.0}])

    result = detect_scenes(
        three_scene_video, workspace_dir, "vid1", speech_margin_seconds=0.5, peak_windows=True
    )

    decode_commands = _decode_commands(recorded_ffmpeg_commands)
    ss_values = sorted(float(cmd[cmd.index("-ss") + 1]) for cmd in decode_commands)
    assert ss_values == pytest.approx([0.0, 5.0])
    assert result["peak_windows"] is True
    saved = json.loads((workspace_dir / "vid1" / "scenes.json").read_text(encoding="utf-8"))
    assert saved["peak_windows"] is True


def test_detect_scenes_with_peak_windows_requires_audio_json(isolated_cwd, three_scene_video):
    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(workspace_dir, "vid1", [{"start": 0.0, "end": 0.5}])

    with pytest.raises(ScenesError, match="audio.json"):
        detect_scenes(three_scene_video, workspace_dir, "vid1", peak_windows=True)
    assert not (workspace_dir / "vid1" / "scenes.json").exists()


def test_detect_scenes_ignores_audio_json_without_peak_windows_byte_for_byte(
    isolated_cwd, three_scene_video, monkeypatch
):
    """R4bis : peak_windows=False (defaut) ignore audio.json meme present :
    scenes.json identique octet pour octet et memes commandes ffmpeg que sans
    audio.json, aucune cle ajoutee."""
    import clipper.scenes as scenes_module
    from clipper.scenes import detect_scenes

    commands: list[list[str]] = []
    real_popen = subprocess.Popen

    def recording_popen(cmd, *args, **kwargs):
        commands.append(list(cmd))
        return real_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(scenes_module.subprocess, "Popen", recording_popen)

    without = isolated_cwd / "without"
    with_audio = isolated_cwd / "with_audio"
    for workspace_dir in (without, with_audio):
        _write_transcript(workspace_dir, "vid1", [{"start": 0.0, "end": 0.5}])
    _write_audio(with_audio, "vid1", [{"timecode": 5.5, "relative_db": 12.0}])

    detect_scenes(three_scene_video, without, "vid1", speech_margin_seconds=0.5)
    commands_without = list(commands)
    commands.clear()
    detect_scenes(three_scene_video, with_audio, "vid1", speech_margin_seconds=0.5, peak_windows=False)

    assert commands == commands_without
    assert (with_audio / "vid1" / "scenes.json").read_bytes() == (without / "vid1" / "scenes.json").read_bytes()
    assert "peak_windows" not in json.loads((without / "vid1" / "scenes.json").read_text(encoding="utf-8"))

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


# --- TASK-e2dc : detection parallele des fenetres, filtre anti-blocs coupe ---


@pytest.fixture
def six_second_color_video(tmp_path):
    """3 plans de 6 s (rouge/bleu/vert, 25 fps) : coupures a 6 s et 12 s."""
    video_path = tmp_path / "long_scenes.mp4"
    _make_color_video(video_path, ["red", "blue", "green"], segment_seconds=6.0)
    return video_path


def test_config_defaults_declares_parallel_detection_options():
    from clipper.scenes import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["detect_parallel"] == 4
    assert CONFIG_DEFAULTS["detect_chunk_seconds"] == 600.0
    assert CONFIG_DEFAULTS["analysis_skip_loop_filter"] is True


def test_detect_parallel_below_one_is_refused(isolated_cwd, three_scene_video):
    from clipper.scenes import ScenesError, detect_scenes

    _full_speech(isolated_cwd / "workspace")
    with pytest.raises(ScenesError, match="detect_parallel"):
        detect_scenes(three_scene_video, isolated_cwd / "workspace", "vid1", detect_parallel=0)


def test_detect_chunk_seconds_not_positive_is_refused(isolated_cwd, three_scene_video):
    from clipper.scenes import ScenesError, detect_scenes

    _full_speech(isolated_cwd / "workspace")
    with pytest.raises(ScenesError, match="detect_chunk_seconds"):
        detect_scenes(three_scene_video, isolated_cwd / "workspace", "vid1", detect_chunk_seconds=0)


def test_chunked_parallel_detection_equals_sequential_one_window(
    isolated_cwd, six_second_color_video
):
    """Une fenetre de 18 s decoupee en morceaux de 5 s (jointures a 5, 10, 15 s,
    aucune sur une coupure reelle) detectee a 4 en parallele : meme liste de
    scenes que le calcul sequentiel, aucune coupure inventee aux jointures."""
    from clipper.scenes import detect_scenes

    _full_speech(isolated_cwd / "ws_seq")
    sequential = detect_scenes(
        six_second_color_video, isolated_cwd / "ws_seq", "vid1",
        detect_parallel=1, detect_chunk_seconds=1e6,
    )
    _full_speech(isolated_cwd / "ws_par")
    parallel = detect_scenes(
        six_second_color_video, isolated_cwd / "ws_par", "vid1",
        detect_parallel=4, detect_chunk_seconds=5.0,
    )
    assert len(sequential["scenes"]) == 3
    assert len(parallel["scenes"]) == 3
    for seq, par in zip(sequential["scenes"], parallel["scenes"]):
        assert par["start"] == pytest.approx(seq["start"], abs=0.05)
        assert par["end"] == pytest.approx(seq["end"], abs=0.05)
    assert len(parallel["frames"]) == len(sequential["frames"])


def test_chunked_detection_splits_a_long_window_into_contiguous_chunks(
    isolated_cwd, six_second_color_video, recorded_ffmpeg_commands
):
    from clipper.scenes import detect_scenes

    _full_speech(isolated_cwd / "workspace")
    detect_scenes(
        six_second_color_video, isolated_cwd / "workspace", "vid1",
        detect_parallel=2, detect_chunk_seconds=5.0,
    )

    commands = _decode_commands(recorded_ffmpeg_commands)
    starts = sorted(float(cmd[cmd.index("-ss") + 1]) for cmd in commands)
    assert starts[:4] == pytest.approx([0.0, 5.0, 10.0, 15.0])
    durations = [float(cmd[cmd.index("-t") + 1]) for cmd in commands]
    assert durations.count(pytest.approx(5.0)) >= 3


def test_windows_are_detected_in_parallel_up_to_detect_parallel(
    isolated_cwd, three_scene_video, monkeypatch
):
    import clipper.scenes as scenes_module

    lock = threading.Lock()
    state = {"running": 0, "peak": 0}

    def fake_decode(video_path, window_start, window_end, *args, **kwargs):
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        time.sleep(0.2)
        with lock:
            state["running"] -= 1
        return [(0.0, window_end - window_start)]

    monkeypatch.setattr(scenes_module, "_decode_window_cuts", fake_decode)
    scenes_module._detect_scene_list(
        three_scene_video, 27.0, 256, 30.0, "",
        [(10.0 * i, 10.0 * i + 1.0) for i in range(6)], "ffmpeg", "ffprobe",
        detect_parallel=3, detect_chunk_seconds=600.0, skip_loop_filter=True,
    )

    assert state["peak"] == 3


def test_failing_window_fails_the_step_naming_the_window(
    isolated_cwd, three_scene_video
):
    """Fenetre 1000-1005 s au-dela de la fin de la video : aucune image
    decodee. L'etape echoue (ScenesError qui nomme la fenetre), sans
    scenes.json partiel ; aucun ffmpeg ne reste en vie."""
    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    _write_transcript(
        workspace_dir, "vid1",
        [{"start": 0.0, "end": 2.0}, {"start": 1000.0, "end": 1005.0}],
    )

    with pytest.raises(ScenesError, match="1000"):
        detect_scenes(
            three_scene_video, workspace_dir, "vid1",
            speech_margin_seconds=0.0, detect_parallel=2,
        )
    assert not (workspace_dir / "vid1" / "scenes.json").exists()


def test_failing_chunk_kills_the_other_ffmpeg_processes(
    isolated_cwd, three_scene_video, monkeypatch
):
    import clipper.scenes as scenes_module

    procs: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def recording_popen(cmd, *args, **kwargs):
        proc = real_popen(cmd, *args, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(scenes_module.subprocess, "Popen", recording_popen)
    _write_transcript(
        isolated_cwd / "workspace", "vid1",
        [{"start": 1000.0, "end": 1005.0}, {"start": 0.0, "end": 6.0}],
    )

    with pytest.raises(scenes_module.ScenesError):
        scenes_module.detect_scenes(
            three_scene_video, isolated_cwd / "workspace", "vid1",
            speech_margin_seconds=0.0, detect_parallel=2,
        )
    assert all(proc.poll() is not None for proc in procs)


def test_skip_loop_filter_only_in_the_detection_command(
    isolated_cwd, three_scene_video, recorded_ffmpeg_commands
):
    from clipper.scenes import detect_scenes

    _full_speech(isolated_cwd / "workspace")
    detect_scenes(three_scene_video, isolated_cwd / "workspace", "vid1")

    detection = _decode_commands(recorded_ffmpeg_commands)
    others = [c for c in recorded_ffmpeg_commands if "rawvideo" not in c]
    assert detection
    for cmd in detection:
        i = cmd.index("-skip_loop_filter")
        assert cmd[i + 1] == "all"
        assert i < cmd.index("-i")
    assert all("-skip_loop_filter" not in cmd for cmd in others)


def test_skip_loop_filter_can_be_turned_off(
    isolated_cwd, three_scene_video, recorded_ffmpeg_commands
):
    from clipper.scenes import detect_scenes

    _full_speech(isolated_cwd / "workspace")
    detect_scenes(
        three_scene_video, isolated_cwd / "workspace", "vid1",
        analysis_skip_loop_filter=False,
    )

    assert all("-skip_loop_filter" not in cmd for cmd in recorded_ffmpeg_commands)


def test_detection_logs_windows_parallelism_and_durations(
    isolated_cwd, three_scene_video, caplog
):
    import logging

    from clipper.scenes import detect_scenes

    _full_speech(isolated_cwd / "workspace")
    with caplog.at_level(logging.INFO, logger="clipper.scenes"):
        detect_scenes(three_scene_video, isolated_cwd / "workspace", "vid1", detect_parallel=2)

    text = " ".join(record.getMessage() for record in caplog.records)
    assert "fenetre" in text and "parallelisme" in text
    assert "detection" in text and "extraction" in text


def test_detect_scenes_interrupted_write_leaves_no_scenes_json(
    isolated_cwd, three_scene_video, monkeypatch
):
    from clipper.scenes import detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    (workspace_dir / "vid1").mkdir(parents=True)
    _full_speech(workspace_dir)

    def failing_replace(*args, **kwargs):
        raise OSError("coupure simulee pendant le remplacement")

    monkeypatch.setattr("os.replace", failing_replace)

    with pytest.raises(OSError):
        detect_scenes(three_scene_video, workspace_dir, "vid1")

    assert not (workspace_dir / "vid1" / "scenes.json").exists()


def test_detect_scenes_truncated_scenes_json_raises_explicit_error_naming_file_and_force(
    isolated_cwd, three_scene_video
):
    from clipper.scenes import ScenesError, detect_scenes

    workspace_dir = isolated_cwd / "workspace"
    video_dir = workspace_dir / "vid1"
    video_dir.mkdir(parents=True)
    (video_dir / "scenes.json").write_text('{"scenes": [{"start": 0.0, "en', encoding="utf-8")

    with pytest.raises(ScenesError) as excinfo:
        detect_scenes(three_scene_video, workspace_dir, "vid1")

    assert "scenes.json" in str(excinfo.value)
    assert "--force" in str(excinfo.value)


# -- TASK-03e7 : scenes plus rapide, meme resultat --


def _noisy_frames(count: int = 120, seed: int = 7):
    """Images bruitees avec des coupes nettes tous les 30 images et des
    variations douces entre deux : des scores proches du seuil, pour que
    toute difference d'arrondi entre deux calculs se voie."""
    import numpy as np

    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, (36, 64, 3), dtype=np.uint8)
    frames = []
    for i in range(count):
        if i % 30 == 0:
            base = rng.integers(0, 256, (36, 64, 3), dtype=np.uint8)
        drift = rng.integers(-6, 7, base.shape)
        frames.append(np.clip(base.astype(np.int16) + drift, 0, 255).astype(np.uint8))
    return frames


def test_fast_detector_gives_the_same_scores_and_cuts_as_the_stock_content_detector():
    """Le calcul de score optimise reste egal, flottant pour flottant, a celui
    de PySceneDetect (meme coupes, memes temps) sur des images bruitees."""
    from scenedetect import FrameTimecode
    from scenedetect.detectors import ContentDetector as StockDetector

    from clipper.scenes import ContentDetector

    frames = _noisy_frames()
    fps = 30000 / 1001
    for threshold in (3.0, 4.0, 27.0):
        stock, fast = StockDetector(threshold=threshold), ContentDetector(threshold=threshold)
        stock_scores, fast_scores = [], []
        stock_cuts, fast_cuts = [], []
        for n, frame in enumerate(frames):
            tc = FrameTimecode(n, fps)
            stock_cuts += stock.process_frame(tc, frame)
            fast_cuts += fast.process_frame(tc, frame)
            stock_scores.append(stock._frame_score)
            fast_scores.append(fast._frame_score)
        end = FrameTimecode(len(frames), fps)
        stock_cuts += stock.post_process(end)
        fast_cuts += fast.post_process(end)
        assert any(score for score in stock_scores), "les scores doivent etre calcules"
        assert fast_scores == stock_scores
        assert [c.frame_num for c in fast_cuts] == [c.frame_num for c in stock_cuts]
        if threshold == 27.0:
            assert len(stock_cuts) >= 3, "les coupes nettes doivent etre detectees"


def test_decode_window_cuts_matches_a_stock_detector_run_on_the_same_pipe(
    isolated_cwd, three_scene_video
):
    """Meme coupes que PySceneDetect branche sur le meme flux ffmpeg."""
    from fractions import Fraction

    import numpy as np
    from scenedetect import FrameTimecode
    from scenedetect.detectors import ContentDetector as StockDetector
    from scenedetect.scene_manager import get_scenes_from_cuts

    from clipper.scenes import _decode_window_cuts

    rate = Fraction(25)
    got = _decode_window_cuts(
        three_scene_video, 0.0, 6.0, 27.0, "", "ffmpeg", 25.0, rate, 64, 48, True
    )

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-skip_loop_filter", "all",
         "-i", str(three_scene_video), "-t", "6.000", "-an",
         "-vf", "fps=25/1,scale=64:48", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    size = 64 * 48 * 3
    detector = StockDetector(threshold=27.0)
    cuts, count = [], 0
    for offset in range(0, len(raw) - size + 1, size):
        frame = np.frombuffer(raw[offset:offset + size], np.uint8).reshape(48, 64, 3)
        cuts += detector.process_frame(FrameTimecode(count, 25.0), frame)
        count += 1
    end = FrameTimecode(count, 25.0)
    cuts += detector.post_process(end)
    expected = get_scenes_from_cuts(
        cut_list=sorted(set(cuts)), start_pos=FrameTimecode(0, 25.0), end_pos=end
    )
    assert got == [(a.seconds, b.seconds) for a, b in expected]
    assert len(got) == 3


def test_config_defaults_declares_extract_batch_and_threads():
    from clipper.scenes import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["extract_batch"] == 8
    assert CONFIG_DEFAULTS["extract_threads"] == 2


def test_extract_threads_below_zero_is_refused(isolated_cwd, three_scene_video):
    from clipper.scenes import ScenesError, detect_scenes

    with pytest.raises(ScenesError, match="extract_threads"):
        detect_scenes(three_scene_video, isolated_cwd / "workspace", "vid1", extract_threads=-1)


def test_extraction_limits_the_decoder_threads_of_each_ffmpeg(
    isolated_cwd, long_scene_video, monkeypatch
):
    import clipper.scenes as scenes_module
    from clipper.scenes import detect_scenes

    commands: list[list[str]] = []
    real_run = scenes_module.subprocess.run

    def recording_run(cmd, *args, **kwargs):
        commands.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(scenes_module.subprocess, "run", recording_run)
    for batch, threads in ((8, 3), (1, 3), (8, 0)):
        commands.clear()
        root = isolated_cwd / f"thr{batch}{threads}"
        _full_speech(root)
        detect_scenes(
            long_scene_video, root, "vid1", keyframe_interval_seconds=2.0,
            extract_batch=batch, extract_threads=threads,
        )
        extraction = [c for c in commands if c[0] == "ffmpeg"]
        assert extraction
        for cmd in extraction:
            inputs = cmd.count("-i")
            if threads:
                assert cmd.count("-threads") == inputs
                assert all(cmd[i + 1] == str(threads) for i, a in enumerate(cmd) if a == "-threads")
            else:
                assert "-threads" not in cmd


def test_extract_batch_below_one_is_refused(isolated_cwd, three_scene_video):
    from clipper.scenes import ScenesError, detect_scenes

    with pytest.raises(ScenesError, match="extract_batch"):
        detect_scenes(three_scene_video, isolated_cwd / "workspace", "vid1", extract_batch=0)


@pytest.fixture
def long_scene_video(tmp_path):
    video_path = tmp_path / "long_scenes.mp4"
    _make_color_video(video_path, ["red", "blue", "green"], segment_seconds=12.0)
    return video_path


def _jpeg_bytes_by_name(result: dict, root: Path) -> dict[str, bytes]:
    return {f["path"]: (root / "vid1" / f["path"]).read_bytes() for f in result["frames"]}


def test_batched_extraction_gives_the_same_scenes_and_the_same_jpeg_bytes(
    isolated_cwd, long_scene_video
):
    """scenes.json et chaque image cle identiques octet pour octet, que les
    images soient extraites une par processus ffmpeg (extract_batch=1) ou par
    lots (8, 1000 : tout dans un seul lot)."""
    from clipper.scenes import detect_scenes

    results, roots = {}, {}
    for batch, threads in ((1, 0), (8, 2), (1000, 5)):
        root = isolated_cwd / f"ws{batch}"
        _full_speech(root)
        results[batch] = detect_scenes(
            long_scene_video, root, "vid1", keyframe_interval_seconds=2.0,
            extract_batch=batch, extract_threads=threads,
        )
        roots[batch] = root

    assert len(results[1]["frames"]) >= 9
    assert results[8] == results[1] == results[1000]
    assert (roots[8] / "vid1" / "scenes.json").read_bytes() == (
        roots[1] / "vid1" / "scenes.json"
    ).read_bytes()
    assert _jpeg_bytes_by_name(results[8], roots[8]) == _jpeg_bytes_by_name(results[1], roots[1])
    assert _jpeg_bytes_by_name(results[1000], roots[1000]) == _jpeg_bytes_by_name(
        results[1], roots[1]
    )


def test_batched_extraction_launches_fewer_ffmpeg_processes(
    isolated_cwd, long_scene_video, monkeypatch
):
    import clipper.scenes as scenes_module
    from clipper.scenes import detect_scenes

    launches: list[list[str]] = []
    real_run = scenes_module.subprocess.run

    def counting_run(cmd, *args, **kwargs):
        launches.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(scenes_module.subprocess, "run", counting_run)

    def extraction_launches(batch: int) -> int:
        launches.clear()
        root = isolated_cwd / f"count{batch}"
        _full_speech(root)
        result = detect_scenes(
            long_scene_video, root, "vid1", keyframe_interval_seconds=2.0, extract_batch=batch
        )
        n_frames = len(result["frames"])
        return n_frames, len([c for c in launches if c[0] == "ffmpeg"])

    n_frames, single = extraction_launches(1)
    _, batched = extraction_launches(8)
    assert single == n_frames
    assert batched == -(-n_frames // 8)


def test_batched_extraction_failure_names_the_timecode(isolated_cwd, long_scene_video):
    from clipper.scenes import ScenesError, detect_scenes

    root = isolated_cwd / "ws"
    _full_speech(root)
    with pytest.raises(ScenesError, match=r"decodeur inexistant_xyz"):
        detect_scenes(
            long_scene_video, root, "vid1", decoder="inexistant_xyz", extract_batch=8
        )
    assert not (root / "vid1" / "scenes.json").exists()
