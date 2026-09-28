from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from clipper import llm, qa
from clipper.config import Config
from clipper.llm.fake import FakeBackend

VIDEO_ID = "abcdefghijk"
CLIP_ID = "01"
TRANSCRIPT = "alors la tu vois il ouvre la porte et la surprise"

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe absents du PATH",
)

pytestmark = needs_ffmpeg


# --------------------------------------------------------------------------
# Fixtures : un clip rendu synthetique (mp4 + JSON au format de render.py)
# --------------------------------------------------------------------------


def make_mp4(path, *, colors=("red",), seg=1.5, size="1080x1920", silence=0.0, audio=True):
    """Video synthetique : un plan de ``seg`` s par couleur (donc un
    changement de plan a chaque couleur), audio sinus precede de ``silence``
    secondes muettes."""
    duration = seg * len(colors)
    args = ["ffmpeg", "-y", "-loglevel", "error"]
    for c in colors:
        args += ["-f", "lavfi", "-i", f"color=c={c}:s={size}:r=30:d={seg}"]
    n = len(colors)
    filters = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    maps = ["-map", "[v]"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}"]
        delay = int(silence * 1000)
        filters += f";[{n}:a]atrim=0:{duration - silence},adelay={delay}|{delay},apad=whole_dur={duration}[a]"
        maps += ["-map", "[a]"]
    args += ["-filter_complex", filters, *maps, "-c:v", "libx264", "-preset", "ultrafast",
             "-pix_fmt", "yuv420p", "-t", str(duration)]
    if audio:
        args += ["-c:a", "aac", "-ar", "48000"]
    args.append(str(path))
    subprocess.run(args, check=True)
    return path


def make_mp4_with_black(path, *, black_seconds, segment_seconds=1.0, size="1080x1920"):
    """Video synthetique : un plan rouge, une plage noire de ``black_seconds``,
    un plan rouge, avec audio continu (pas de silence)."""
    total = round(segment_seconds * 2 + black_seconds, 3)
    args = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=red:s={size}:r=30:d={segment_seconds}",
        "-f", "lavfi", "-i", f"color=c=black:s={size}:r=30:d={black_seconds}",
        "-f", "lavfi", "-i", f"color=c=red:s={size}:r=30:d={segment_seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={total}",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-map", "3:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-t", str(total),
        "-c:a", "aac", "-ar", "48000", str(path),
    ]
    subprocess.run(args, check=True)
    return total


def write_black_clip(output_dir, *, black_seconds, segment_seconds=1.0, clip_id=CLIP_ID, size="1080x1920"):
    d = output_dir / VIDEO_ID
    total = make_mp4_with_black(
        d / f"{clip_id}.mp4", black_seconds=black_seconds, segment_seconds=segment_seconds, size=size,
    )
    (d / f"{clip_id}.json").write_text(
        json.dumps(clip_json(duration=total, clip_id=clip_id)), encoding="utf-8"
    )
    return d / f"{clip_id}.json"


LETTERBOX_RECT = {"x": 0, "y": 440, "w": 1080, "h": 790}


def make_letterbox_mp4(path, *, black_seconds, segment_seconds=1.0, size="1080x1920", video_rect=LETTERBOX_RECT):
    """Video synthetique letterbox : fond blanc (encadre du titre d'ecran
    compris) sur tout le cadre, avec un rectangle rouge/noir/rouge dessine
    dans ``video_rect`` seulement -> le noir n'occupe qu'une fraction du
    cadre entier (la part blanche domine), seul un blackdetect restreint a
    ``video_rect`` peut le voir."""
    total = round(segment_seconds * 2 + black_seconds, 3)
    x, y, w, h = video_rect["x"], video_rect["y"], video_rect["w"], video_rect["h"]

    def seg(color, dur):
        return f"color=c=white:s={size}:r=30:d={dur},drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=fill"

    args = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", seg("red", segment_seconds),
        "-f", "lavfi", "-i", seg("black", black_seconds),
        "-f", "lavfi", "-i", seg("red", segment_seconds),
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={total}",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-map", "3:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-t", str(total),
        "-c:a", "aac", "-ar", "48000", str(path),
    ]
    subprocess.run(args, check=True)
    return total


def write_letterbox_clip(
    output_dir, *, black_seconds, segment_seconds=1.0, clip_id=CLIP_ID, size="1080x1920", video_rect=LETTERBOX_RECT,
):
    d = output_dir / VIDEO_ID
    total = make_letterbox_mp4(
        d / f"{clip_id}.mp4", black_seconds=black_seconds, segment_seconds=segment_seconds,
        size=size, video_rect=video_rect,
    )
    (d / f"{clip_id}.json").write_text(
        json.dumps(clip_json(
            duration=total, clip_id=clip_id, layout="letterbox", video_rect=video_rect,
            screen_title="Il ouvre la porte",
        )),
        encoding="utf-8",
    )
    return d / f"{clip_id}.json"


def write_clip_letterbox(
    output_dir, clip_id=CLIP_ID, *, video_rect=LETTERBOX_RECT,
    screen_title="Il ouvre la porte, regarde bien", hook_text="ignore-moi", **mp4_kwargs
):
    """Clip letterbox sans video specifique (aucun controle blackdetect
    teste ici) : sert aux tests de prompt/schema envoyes a l'IA."""
    d = output_dir / VIDEO_ID
    colors = mp4_kwargs.get("colors", ("red",))
    duration = mp4_kwargs.get("seg", 1.5) * len(colors)
    make_mp4(d / f"{clip_id}.mp4", **mp4_kwargs)
    (d / f"{clip_id}.json").write_text(
        json.dumps(clip_json(
            duration=duration, clip_id=clip_id, layout="letterbox", video_rect=video_rect,
            screen_title=screen_title, hook_text=hook_text,
        )),
        encoding="utf-8",
    )
    return d / f"{clip_id}.json"


def clip_json(duration=3.0, **overrides):
    """Le sidecar tel que l'ecrit clipper/render.py (SPEC-6127)."""
    data = {
        "video_id": VIDEO_ID, "source_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "source_title": "Une video", "clip_id": CLIP_ID, "part": 1, "parts_total": 1,
        "start": 10.0, "end": 10.0 + duration, "duration": duration, "language": "fr",
        "score": 80.0, "scores": {"hook": 8}, "reason": "ca marche", "hook_text": "Il ouvre la porte",
        "title": "Titre", "caption": "Legende", "hashtags": ["#un"], "transcript": TRANSCRIPT,
        "layout": "single", "qa": {"status": "skipped", "issues": []},
        "created_at": "2026-09-25T10:00:00+00:00",
    }
    data.update(overrides)
    return data


@pytest.fixture
def dirs(tmp_path):
    out = tmp_path / "output" / VIDEO_ID
    out.mkdir(parents=True)
    return tmp_path / "workspace", tmp_path / "output"


def write_clip(output_dir, clip_id=CLIP_ID, **mp4_kwargs):
    d = output_dir / VIDEO_ID
    colors = mp4_kwargs.get("colors", ("red",))
    duration = mp4_kwargs.get("seg", 1.5) * len(colors)
    make_mp4(d / f"{clip_id}.mp4", **mp4_kwargs)
    (d / f"{clip_id}.json").write_text(
        json.dumps(clip_json(duration=duration, clip_id=clip_id)), encoding="utf-8"
    )
    return d / f"{clip_id}.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def config(tmp_path, **qa_overrides):
    return Config(
        mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={"qa": qa_overrides} if qa_overrides else {},
    )


def no_issue(_request=None):
    return {"issues": []}


def run(tmp_path, workspace, output, **kwargs):
    return qa.run(VIDEO_ID, workspace, output, config=config(tmp_path), **kwargs)


# --------------------------------------------------------------------------
# C1-C2 : images (debut, milieu, fin, une par changement de plan) et
# transcription envoyees a clipper.llm, usage qa
# --------------------------------------------------------------------------


def test_llm_receives_start_middle_end_frames_and_one_per_shot_change(tmp_path, dirs):
    workspace, output = dirs
    write_clip(output, colors=("red", "blue", "green"), seg=1.5)  # 2 changements de plan
    fake = FakeBackend([no_issue])
    with llm.use_backend(fake):
        run(tmp_path, workspace, output)

    assert len(fake.calls) == 1
    request = fake.calls[0]
    assert request.usage == "qa"
    # debut, milieu, fin + 2 changements de plan (a 1.5 s et 3.0 s)
    assert len(request.images) == 5
    for image in request.images:
        assert image.suffix == ".jpg"
        assert image.exists()
    # le prompt annonce chaque image jointe : « Image k : t=<s> s ... »
    timecodes = [float(t) for t in re.findall(r"Image \d+ : t=(\d+\.\d+) s", request.prompt)]
    assert len(timecodes) == 5
    assert timecodes[0] < 0.5
    assert any(abs(t - 2.25) < 0.3 for t in timecodes)
    assert timecodes[-1] > 4.0
    assert any(1.5 <= t < 2.0 for t in timecodes)
    assert any(3.0 <= t < 3.5 for t in timecodes)


def test_prompt_carries_clip_transcript_and_hook(tmp_path, dirs):
    workspace, output = dirs
    write_clip(output)
    fake = FakeBackend([no_issue])
    with llm.use_backend(fake):
        run(tmp_path, workspace, output)
    assert TRANSCRIPT in fake.calls[0].prompt
    assert "Il ouvre la porte" in fake.calls[0].prompt


def test_schema_asks_for_the_four_defects_black_screen_excluded(tmp_path, dirs):
    workspace, output = dirs
    write_clip(output)
    fake = FakeBackend([no_issue])
    with llm.use_backend(fake):
        run(tmp_path, workspace, output)
    enum = fake.calls[0].schema["properties"]["issues"]["items"]["properties"]["type"]["enum"]
    assert set(enum) == {"face_cut", "subtitle_on_face", "starts_mid_sentence", "weak_hook"}
    assert "black_screen" not in qa.DEFECTS


# --------------------------------------------------------------------------
# C4-C5 : qa.status passed | rejected + issues dans le JSON ; rejete jamais pret
# --------------------------------------------------------------------------


def test_clean_clip_is_passed_and_ready(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    data = read(path)
    assert data["qa"]["status"] == "passed"
    assert data["qa"]["issues"] == []
    assert data["ready"] is True
    assert qa.is_ready(data) is True
    # le reste du sidecar est intact
    assert data["title"] == "Titre" and data["transcript"] == TRANSCRIPT


def test_llm_defect_rejects_clip_and_it_is_never_ready(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output)
    answer = {"issues": [{"type": "face_cut", "detail": "le visage sort du cadre a droite"}]}
    with llm.use_backend(FakeBackend([answer])):
        run(tmp_path, workspace, output)
    data = read(path)
    assert data["qa"]["status"] == "rejected"
    assert data["qa"]["issues"] == [
        {"type": "face_cut", "detail": "le visage sort du cadre a droite", "source": "llm"}
    ]
    assert data["ready"] is False
    assert qa.is_ready(data) is False


def test_is_ready_false_for_rejected_even_if_ready_flag_forged():
    forged = clip_json(qa={"status": "rejected", "issues": [{"type": "weak_hook"}]}, ready=True)
    assert qa.is_ready(forged) is False
    assert qa.is_ready(clip_json()) is False  # skipped : pas controle, pas pret


def test_every_rendered_clip_of_the_video_is_checked(tmp_path, dirs):
    workspace, output = dirs
    a = write_clip(output, clip_id="01")
    b = write_clip(output, clip_id="02-p1")
    bad = {"issues": [{"type": "weak_hook", "detail": "accroche plate"}]}
    with llm.use_backend(FakeBackend([no_issue, bad])):
        run(tmp_path, workspace, output)
    assert read(a)["qa"]["status"] == "passed"
    assert read(b)["qa"]["status"] == "rejected"


def test_invalid_llm_answer_raises_and_leaves_json_untouched(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output)
    before = path.read_text(encoding="utf-8")
    with llm.use_backend(FakeBackend([{"issues": [{"type": "pas_un_defaut", "detail": "x"}]}])):
        with pytest.raises(llm.SchemaError):
            run(tmp_path, workspace, output)
    assert path.read_text(encoding="utf-8") == before


def test_llm_unavailable_raises_no_fallback_verdict(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output)
    with llm.use_backend(FakeBackend([llm.TransientLLMError("quota")])):
        with pytest.raises(llm.TransientLLMError):
            run(tmp_path, workspace, output)
    assert read(path)["qa"]["status"] == "skipped"
    assert "ready" not in read(path)


def test_already_checked_clip_is_not_rechecked_unless_force(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    with llm.use_backend(FakeBackend([])) as fake:
        run(tmp_path, workspace, output)
    assert fake.calls == []
    bad = {"issues": [{"type": "weak_hook", "detail": "plat"}]}
    with llm.use_backend(FakeBackend([bad])):
        run(tmp_path, workspace, output, force=True)
    assert read(path)["qa"]["status"] == "rejected"


def test_missing_output_raises(tmp_path):
    with pytest.raises(qa.QAError):
        qa.run(VIDEO_ID, tmp_path / "workspace", tmp_path / "output", config=config(tmp_path))


def test_mp4_missing_for_json_raises(tmp_path, dirs):
    workspace, output = dirs
    (output / VIDEO_ID / "01.json").write_text(json.dumps(clip_json()), encoding="utf-8")
    with llm.use_backend(FakeBackend([])):
        with pytest.raises(qa.QAError):
            run(tmp_path, workspace, output)


# --------------------------------------------------------------------------
# C6 : verifications mecaniques locales (duree, resolution, silence initial)
# --------------------------------------------------------------------------


def local_types(path):
    return {i["type"] for i in read(path)["qa"]["issues"] if i["source"] == "local"}


def test_wrong_resolution_rejects_even_if_llm_passes(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output, size="720x1280")
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert read(path)["qa"]["status"] == "rejected"
    assert local_types(path) == {"resolution"}
    assert read(path)["ready"] is False


def test_leading_silence_over_one_second_rejects(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output, colors=("red", "blue"), seg=1.5, silence=1.5)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert read(path)["qa"]["status"] == "rejected"
    assert local_types(path) == {"leading_silence"}


def test_short_leading_silence_is_fine(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output, colors=("red", "blue"), seg=1.5, silence=0.5)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert read(path)["qa"]["status"] == "passed"


def test_no_audio_stream_counts_as_leading_silence(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output, audio=False)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert local_types(path) == {"leading_silence"}


def test_duration_mismatch_with_json_rejects(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output)  # 1.5 s reels
    data = read(path)
    data["duration"] = 30.0
    path.write_text(json.dumps(data), encoding="utf-8")
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert local_types(path) == {"duration"}
    assert read(path)["qa"]["status"] == "rejected"


def test_local_and_llm_issues_are_combined(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output, size="720x1280")
    bad = {"issues": [{"type": "starts_mid_sentence", "detail": "commence par 'et donc'"}]}
    with llm.use_backend(FakeBackend([bad])):
        run(tmp_path, workspace, output)
    sources = sorted((i["source"], i["type"]) for i in read(path)["qa"]["issues"])
    assert sources == [("llm", "starts_mid_sentence"), ("local", "resolution")]


def test_local_thresholds_come_from_config(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output, colors=("red", "blue"), seg=1.5, silence=1.5)
    with llm.use_backend(FakeBackend([no_issue])):
        qa.run(VIDEO_ID, workspace, output, config=config(tmp_path, max_leading_silence=2.0))
    assert read(path)["qa"]["status"] == "passed"


# --------------------------------------------------------------------------
# TASK-2960 : ecran noir mesure localement (ffmpeg blackdetect), un fondu
# court de la source n'est pas un rejet
# --------------------------------------------------------------------------


def test_short_black_fade_under_threshold_is_not_rejected(tmp_path, dirs):
    workspace, output = dirs
    path = write_black_clip(output, black_seconds=0.4)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert "black_screen" not in local_types(path)
    assert read(path)["qa"]["status"] == "passed"


def test_black_segment_over_threshold_is_rejected_locally(tmp_path, dirs):
    workspace, output = dirs
    path = write_black_clip(output, black_seconds=1.5)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert local_types(path) == {"black_screen"}
    assert read(path)["qa"]["status"] == "rejected"
    assert read(path)["ready"] is False


def test_clip_without_black_frames_has_no_black_screen_issue(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output, colors=("red", "blue"), seg=1.0)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert "black_screen" not in local_types(path)
    assert read(path)["qa"]["status"] == "passed"


def test_black_min_seconds_is_configurable(tmp_path, dirs):
    workspace, output = dirs
    path = write_black_clip(output, black_seconds=1.5)
    with llm.use_backend(FakeBackend([no_issue])):
        qa.run(VIDEO_ID, workspace, output, config=config(tmp_path, black_min_seconds=2.0))
    assert "black_screen" not in local_types(path)
    assert read(path)["qa"]["status"] == "passed"


def test_ffmpeg_failure_on_black_detection_raises_no_fallback_verdict(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output)
    before = path.read_text(encoding="utf-8")
    with llm.use_backend(FakeBackend([no_issue])):
        with pytest.raises(qa.QAError):
            run(tmp_path, workspace, output, ffmpeg_bin="ffmpeg-binaire-absent")
    assert path.read_text(encoding="utf-8") == before


# --------------------------------------------------------------------------
# TASK-2fc8 : controles adaptes au format letterbox (SPEC-6127)
# --------------------------------------------------------------------------


def test_letterbox_schema_excludes_face_cut_and_subtitle_on_face(tmp_path, dirs):
    workspace, output = dirs
    write_clip_letterbox(output)
    fake = FakeBackend([no_issue])
    with llm.use_backend(fake):
        run(tmp_path, workspace, output)
    enum = fake.calls[0].schema["properties"]["issues"]["items"]["properties"]["type"]["enum"]
    assert set(enum) == {"starts_mid_sentence", "weak_hook"}


def test_letterbox_prompt_uses_screen_title_not_hook_and_describes_format(tmp_path, dirs):
    workspace, output = dirs
    write_clip_letterbox(output, screen_title="Alerte ceci va vous surprendre", hook_text="ignore-moi")
    fake = FakeBackend([no_issue])
    with llm.use_backend(fake):
        run(tmp_path, workspace, output)
    prompt = fake.calls[0].prompt
    assert "Alerte ceci va vous surprendre" in prompt
    assert "ignore-moi" not in prompt
    assert "encadre blanc" in prompt
    assert "video" in prompt.lower()
    assert "sous-titres" in prompt


def test_letterbox_without_video_rect_raises(tmp_path, dirs):
    workspace, output = dirs
    path = write_clip(output)  # layout "single" par defaut, sans video_rect
    data = read(path)
    data["layout"] = "letterbox"
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    with llm.use_backend(FakeBackend([])):
        with pytest.raises(qa.QAError):
            run(tmp_path, workspace, output)
    assert path.read_text(encoding="utf-8") == before


def test_letterbox_black_screen_measured_on_video_rect_only(tmp_path, dirs):
    workspace, output = dirs
    path = write_letterbox_clip(output, black_seconds=1.5)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert local_types(path) == {"black_screen"}
    assert read(path)["qa"]["status"] == "rejected"
    assert read(path)["ready"] is False


def test_letterbox_short_black_in_video_rect_is_not_rejected(tmp_path, dirs):
    workspace, output = dirs
    path = write_letterbox_clip(output, black_seconds=0.4)
    with llm.use_backend(FakeBackend([no_issue])):
        run(tmp_path, workspace, output)
    assert "black_screen" not in local_types(path)
    assert read(path)["qa"]["status"] == "passed"
