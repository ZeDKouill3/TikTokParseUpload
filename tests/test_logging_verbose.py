"""TASK-8abc : sortie console plus verbeuse (-v/-vv).

Un clause du done_criteria par groupe de tests, preuve par caplog (jamais un
print) que les lignes annoncees sont bien emises, au bon niveau, et a une
frequence bornee pour les etapes longues (au plus toutes les 30 s ou tous les
10 %).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from clipper import llm
from clipper.config import Config
from clipper.llm import SchemaError
from clipper.llm.fake import FakeBackend

COLOR_SCHEMA = {
    "type": "object",
    "properties": {"couleur": {"type": "string"}},
    "required": ["couleur"],
    "additionalProperties": False,
}


def make_llm_config(**llm_table) -> Config:
    return Config(
        mode="review", workspace_dir=Path("workspace"), output_dir=Path("output"),
        _sections={"llm": llm_table} if llm_table else {},
    )


def at_most_two_letters(value):
    if len(value["couleur"]) > 2:
        raise SchemaError(f"couleur de {len(value['couleur'])} lettres, 2 au plus")


# --------------------------------------------------------------------------
# clipper.llm : une ligne par appel LLM.
# --------------------------------------------------------------------------


def test_ask_logs_one_info_line_naming_usage_model_and_success(caplog):
    fake = FakeBackend([{"couleur": "rouge"}])
    with llm.use_backend(fake), caplog.at_level(logging.INFO, logger="clipper.llm"):
        llm.ask("vision", "p", [], COLOR_SCHEMA, config=make_llm_config())

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(lines) == 1
    assert "vision" in lines[0]
    assert fake.calls[0].model in lines[0]
    assert "reussi" in lines[0]


def test_ask_logs_a_retry_line_then_a_success_line(caplog):
    fake = FakeBackend([{"couleur": "rouge"}, {"couleur": "or"}])
    with llm.use_backend(fake), caplog.at_level(logging.INFO, logger="clipper.llm"):
        llm.ask(
            "vision", "Quelle couleur ?", [], COLOR_SCHEMA,
            config=make_llm_config(), check=at_most_two_letters,
        )

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(fake.calls) == 2
    assert len(lines) == 2
    assert "reessai" in lines[0]
    assert "reussi" in lines[1]


def test_ask_logs_failure_line_when_finally_refused(caplog):
    fake = FakeBackend([{"couleur": "rouge"}, {"couleur": "violet"}])
    with llm.use_backend(fake), caplog.at_level(logging.INFO, logger="clipper.llm"):
        with pytest.raises(SchemaError):
            llm.ask(
                "qa", "p", [], COLOR_SCHEMA, config=make_llm_config(),
                check=at_most_two_letters,
            )

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("echec" in line and "qa" in line for line in lines)


def test_ask_logs_nothing_below_info_level(caplog):
    fake = FakeBackend([{"couleur": "rouge"}])
    with llm.use_backend(fake), caplog.at_level(logging.WARNING, logger="clipper.llm"):
        llm.ask("vision", "p", [], COLOR_SCHEMA, config=make_llm_config())

    assert caplog.records == []


def test_ask_debug_level_adds_a_line_per_backend_call_before_the_outcome(caplog):
    fake = FakeBackend([{"couleur": "rouge"}])
    with llm.use_backend(fake), caplog.at_level(logging.DEBUG, logger="clipper.llm"):
        llm.ask("vision", "p", [], COLOR_SCHEMA, config=make_llm_config())

    debug_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("vision" in line for line in debug_lines)


# --------------------------------------------------------------------------
# clipper.pipeline : debut/fin de chaque etape avec duree, clip i/N pour
# reframe/render, resume final. Toutes les vraies etapes sont remplacees par
# de petits faux qui ecrivent juste ce que le code de pipeline.py lit
# ensuite (ADR-b16b : pipeline.py ne fait ici que son travail d'orchestrateur,
# les vraies etapes sont testees ailleurs) : aucun ffmpeg, GPU ni reseau.
# --------------------------------------------------------------------------

PIPE_VIDEO_ID = "abcdefghijk"
PIPE_URL = f"https://www.youtube.com/watch?v={PIPE_VIDEO_ID}"


def _pipeline_config(tmp_path: Path) -> Config:
    return Config(mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")


def _install_fake_steps(monkeypatch, clip_ids=("03-p1",)):
    """Remplace chaque module d'etape par un faux minimal, sans toucher a
    clipper.pipeline lui-meme (le code sous test) : c'est lui qui appelle ces
    fonctions, en boucle pour reframe/render (une entree par clip)."""
    from clipper import pipeline

    monkeypatch.setattr(pipeline.download, "download", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.transcribe, "transcribe", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.scenes, "detect_scenes", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.audio, "run", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.moments, "run", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.vision, "run", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.parts, "run", lambda *a, **k: None)

    def fake_captions_run(video_id, ws, *, config, force, **opts):
        d = Path(ws) / video_id
        d.mkdir(parents=True, exist_ok=True)
        clips = [{"id": cid, "start": 0.0, "end": 10.0} for cid in clip_ids]
        (d / "captions.json").write_text(json.dumps({"clips": clips}), encoding="utf-8")

    monkeypatch.setattr(pipeline.captions, "run", fake_captions_run)

    def fake_reframe(video_id, clip_id, start, end, ws, *, config, force, **opts):
        d = Path(ws) / video_id / "reframe"
        d.mkdir(parents=True, exist_ok=True)
        plan = {
            "layout": "letterbox", "output": {"width": 1080, "height": 1920},
            "text_zones": {"subtitles": {"x": 0, "y": 1700, "w": 1080, "h": 200}},
            "plans": [],
        }
        (d / f"{clip_id}.json").write_text(json.dumps(plan), encoding="utf-8")

    monkeypatch.setattr(pipeline.reframe, "reframe", fake_reframe)
    monkeypatch.setattr(pipeline.subtitles, "generate", lambda *a, **k: None)

    def fake_render(video_id, clip_id, ws, out, *, config, force, **opts):
        d = Path(out) / video_id
        d.mkdir(parents=True, exist_ok=True)
        data = {"video_id": video_id, "clip_id": clip_id, "duration": 10.0,
                "qa": {"status": "skipped", "issues": []}, "ready": False}
        (d / f"{clip_id}.json").write_text(json.dumps(data), encoding="utf-8")
        (d / f"{clip_id}.mp4").write_bytes(b"")

    monkeypatch.setattr(pipeline.render_step, "render", fake_render)

    def fake_qa_run(video_id, ws, out, *, config, force, **opts):
        d = Path(out) / video_id
        for cid in clip_ids:
            p = d / f"{cid}.json"
            data = json.loads(p.read_text(encoding="utf-8"))
            data["qa"] = {"status": "passed", "issues": []}
            data["ready"] = True
            p.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(pipeline.qa, "run", fake_qa_run)


def _run_fake_pipeline(tmp_path, monkeypatch, clip_ids=("03-p1",)):
    from clipper import pipeline

    _install_fake_steps(monkeypatch, clip_ids=clip_ids)
    config = _pipeline_config(tmp_path)
    return pipeline.run(PIPE_URL, config=config)


def test_run_logs_start_and_duration_for_every_step(tmp_path, monkeypatch, caplog):
    from clipper import pipeline

    with caplog.at_level(logging.INFO, logger="clipper.pipeline"):
        state = _run_fake_pipeline(tmp_path, monkeypatch)

    assert state["status"] == "done"
    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    for name in pipeline.STEPS:
        assert any(f"etape {name}" in line and "terminee" not in line for line in lines), name
        done_lines = [line for line in lines if f"etape {name} terminee en" in line]
        assert done_lines, f"pas de ligne de fin pour {name} : {lines}"
        assert done_lines[0].rstrip().endswith("s")


def test_run_logs_clip_progress_for_reframe_and_render(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="clipper.pipeline"):
        _run_fake_pipeline(tmp_path, monkeypatch, clip_ids=("03-p1",))

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("reframe clip 1/1" in line and "03-p1" in line for line in lines)
    assert any("render clip 1/1" in line and "03-p1" in line for line in lines)


def test_run_clip_progress_debug_logs_every_clip_even_when_info_is_throttled(tmp_path, monkeypatch, caplog):
    """Avec beaucoup de clips, INFO ne montre pas chaque clip (throttle a
    10 %) mais DEBUG si (-vv, done_criteria de TASK-8abc)."""
    clip_ids = tuple(f"{n:02d}-p1" for n in range(1, 21))  # 20 clips : pas de piste, 10 % = 2

    with caplog.at_level(logging.DEBUG, logger="clipper.pipeline"):
        _run_fake_pipeline(tmp_path, monkeypatch, clip_ids=clip_ids)

    debug_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    info_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    debug_reframe = [line for line in debug_lines if line.startswith(f"{PIPE_VIDEO_ID} : reframe clip")]
    info_reframe = [line for line in info_lines if line.startswith(f"{PIPE_VIDEO_ID} : reframe clip")]
    assert len(debug_reframe) == 20
    assert 1 < len(info_reframe) < 20


def test_run_summary_reports_durations_clip_count_qa_status_and_output_path(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="clipper.pipeline"):
        state = _run_fake_pipeline(tmp_path, monkeypatch, clip_ids=("03-p1", "04-p1"))

    assert state["status"] == "done"
    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    summary = [line for line in lines if line.startswith(f"{PIPE_VIDEO_ID} : termine - ")]
    assert len(summary) == 1
    line = summary[0]
    assert "2 clip(s)" in line
    assert "'passed': 2" in line
    for name in ("download", "transcribe", "scenes", "audio", "moments", "vision", "parts",
                 "captions", "reframe", "subtitles", "render", "qa"):
        assert f"'{name}'" in line
    assert str(tmp_path / "output" / PIPE_VIDEO_ID) in line


# --------------------------------------------------------------------------
# clipper.moments : nombre de candidats, retenus, raison des rejets ; decision
# du jury par candidat (score final, retenu/rejete/exploration).
# --------------------------------------------------------------------------

MOMENTS_VIDEO_ID = "abcdefghijk"

MOMENTS_RUBRIC = """
min_score = 60
max_moments_per_hour = 1000
always_keep_score = 1000
trend_keywords = []

[criteria.hook]
weight = 1
question = "Accroche ?"

[durations]
single_min = 2
single_max = 20
part_min = 60
part_max = 90
min_parts = 2
max_parts = 12
tolerance = 1

[bonus]
max_total = 0
replayed = 0
audio_peaks = 0
audio_peaks_full = 1
visual = 0

[exclusions]
sponsorblock_categories = []
"""


def _moments_sentence(k: int) -> dict:
    words = [{"word": f" mot{k}_{i}" + ("." if i == 3 else ""), "start": 5 * k + i * 0.9,
              "end": 5 * k + i * 0.9 + 0.8, "probability": 0.9} for i in range(4)]
    return {"id": k, "start": words[0]["start"], "end": words[-1]["end"],
            "text": "".join(w["word"] for w in words), "words": words}


def _moments_video_dir(tmp_path: Path, n_sentences: int = 6) -> Path:
    d = tmp_path / "workspace" / MOMENTS_VIDEO_ID
    d.mkdir(parents=True)
    meta = {"video_id": MOMENTS_VIDEO_ID, "title": "t", "description": "d", "duration": 500.0,
            "chapters": [], "heatmap": [], "sponsorblock_segments": []}
    transcript = {"video_id": MOMENTS_VIDEO_ID, "language": "fr",
                  "segments": [_moments_sentence(k) for k in range(n_sentences)]}
    audio = {"window_seconds": 1.0, "energy_db": [], "peaks": []}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
    (d / "audio.json").write_text(json.dumps(audio), encoding="utf-8")
    return d


def _moments_config(tmp_path: Path, rubric_path: Path, mode="review", **moments) -> Config:
    return Config(
        mode=mode, workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={"moments": {"rubric_path": str(rubric_path), **moments}},
    )


def _moment(start, end, scores):
    return {"start": start, "end": end, "hook_text": "accroche", "justification": "ca marche",
            "format": "single", "part_breaks": [], "scores": scores}


def test_moments_run_logs_candidate_and_rejection_counts(tmp_path, caplog):
    from clipper.moments import run as run_moments

    _moments_video_dir(tmp_path)
    rubric_path = tmp_path / "rubric.toml"
    rubric_path.write_text(MOMENTS_RUBRIC, encoding="utf-8")
    config = _moments_config(tmp_path, rubric_path)
    kept = _moment(0.0, 4.7, {"hook": 10})
    weak = _moment(20.0, 24.7, {"hook": 0})
    fake = FakeBackend([{"moments": [kept, weak]}])

    with llm.use_backend(fake), caplog.at_level(logging.INFO, logger="clipper.moments"):
        run_moments(MOMENTS_VIDEO_ID, tmp_path / "workspace", config=config)

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    summary = [line for line in lines if "moments -" in line]
    assert len(summary) == 1
    assert "2 candidats notes" in summary[0]
    assert "1 retenus" in summary[0]
    assert "1 rejetes" in summary[0]


def _jury_answer(request):
    if request.usage == "moments":
        return {"moments": [_moment(0.0, 4.7, {"hook": 10})]}
    item = request.schema["properties"]["candidates"]["items"]["properties"]
    candidates = []
    for ref in item["ref"]["enum"]:
        entry = {"ref": ref, "argument": "accroche nette", "scores": {"hook": 10}}
        if "veto" in item:
            entry.update(veto=False, veto_reason="")
        candidates.append(entry)
    return {"candidates": candidates}


def test_moments_jury_selection_logs_a_decision_per_candidate(tmp_path, caplog):
    from clipper.moments import run as run_moments

    _moments_video_dir(tmp_path)
    rubric_path = tmp_path / "rubric.toml"
    rubric_path.write_text(MOMENTS_RUBRIC, encoding="utf-8")
    config = _moments_config(tmp_path, rubric_path, mode="auto")
    fake = FakeBackend([_jury_answer] * 500)

    with llm.use_backend(fake), caplog.at_level(logging.INFO, logger="clipper.moments"):
        run_moments(MOMENTS_VIDEO_ID, tmp_path / "workspace", config=config)

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    jury_lines = [line for line in lines if "jury [" in line]
    assert len(jury_lines) == 1
    assert "retenu" in jury_lines[0]


# --------------------------------------------------------------------------
# clipper.vision : progression par lot d'images (moment i/N).
# --------------------------------------------------------------------------

VISION_VIDEO_ID = "abcdefghijk"


def _vision_frame(video_dir: Path, t: float) -> str:
    (video_dir / "frames").mkdir(exist_ok=True)
    path = f"frames/f{int(t)}.jpg"
    cv2.imwrite(str(video_dir / path), np.zeros((32, 32, 3), dtype="uint8"))
    return path


def _vision_video_dir(tmp_path: Path, timecodes) -> Path:
    d = tmp_path / "workspace" / VISION_VIDEO_ID
    d.mkdir(parents=True)
    frames = [{"path": _vision_frame(d, t), "timecode": t, "scene": n} for n, t in enumerate(timecodes)]
    (d / "scenes.json").write_text(json.dumps({"scenes": [], "frames": frames}), encoding="utf-8")
    rubric_path = tmp_path / "rubric.toml"
    rubric_path.write_text("[bonus]\nvisual = 2\nmax_total = 6\n", encoding="utf-8")
    moments = {
        "video_id": VISION_VIDEO_ID,
        "rubric": {"path": str(rubric_path), "min_score": 60},
        "moments": [{"id": 0, "start": timecodes[0], "end": timecodes[-1], "hook_text": "a"}],
        "rejected": [],
    }
    (d / "moments.json").write_text(json.dumps(moments), encoding="utf-8")
    return d


def _vision_answer(request):
    frames = []
    for index_str, _ in re.findall(r"Image (\d+) : ([\d.]+) s", request.prompt):
        frames.append({"index": int(index_str), "description": "une image", "tags": [], "striking": False})
    return {"frames": frames}


def test_vision_run_logs_batch_progress(tmp_path, caplog):
    from clipper.vision import run as run_vision

    timecodes = [float(n) for n in range(10)]
    _vision_video_dir(tmp_path, timecodes)
    config = Config(
        mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={"vision": {"batch_size": 1, "parallel": 1, "window_seconds": 1}},
    )
    fake = FakeBackend([_vision_answer] * 500)

    with llm.use_backend(fake), caplog.at_level(logging.DEBUG, logger="clipper.vision"):
        run_vision(VISION_VIDEO_ID, tmp_path / "workspace", config=config)

    debug_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    info_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    vision_debug = [line for line in debug_lines if "vision lot" in line]
    vision_info = [line for line in info_lines if "vision lot" in line]
    assert len(vision_debug) == len(timecodes)
    assert vision_info, "aucune ligne INFO de progression vision"
    assert vision_info[-1].endswith(f"{len(timecodes)}/{len(timecodes)}")


# --------------------------------------------------------------------------
# clipper.qa : clip i/N avec duree.
# --------------------------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe absents du PATH",
)

QA_VIDEO_ID = "abcdefghijk"


def _qa_clip_json(clip_id: str, duration: float) -> dict:
    return {
        "video_id": QA_VIDEO_ID, "source_url": f"https://www.youtube.com/watch?v={QA_VIDEO_ID}",
        "source_title": "Une video", "clip_id": clip_id, "part": 1, "parts_total": 1,
        "start": 10.0, "end": 10.0 + duration, "duration": duration, "language": "fr",
        "score": 80.0, "scores": {"hook": 8}, "reason": "ca marche", "hook_text": "accroche",
        "title": "Titre", "caption": "Legende", "hashtags": ["#un"], "transcript": "un peu de texte",
        "layout": "single", "qa": {"status": "skipped", "issues": []},
        "created_at": "2026-09-25T10:00:00+00:00",
    }


def _write_qa_clip(output_dir: Path, clip_id: str, seg: float = 1.0) -> Path:
    d = output_dir / QA_VIDEO_ID
    d.mkdir(parents=True, exist_ok=True)
    mp4 = d / f"{clip_id}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=red:s=1080x1920:r=30:d={seg}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seg}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-t", str(seg),
        "-c:a", "aac", "-ar", "48000", str(mp4),
    ], check=True)
    path = d / f"{clip_id}.json"
    path.write_text(json.dumps(_qa_clip_json(clip_id, seg)), encoding="utf-8")
    return path


def _qa_config(tmp_path: Path, **qa_overrides) -> Config:
    return Config(
        mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={"qa": {"parallel": 1, **qa_overrides}},
    )


@needs_ffmpeg
def test_qa_run_logs_clip_progress_with_duration(tmp_path, caplog):
    from clipper import qa

    output_dir = tmp_path / "output"
    _write_qa_clip(output_dir, "01")
    _write_qa_clip(output_dir, "02")
    fake = FakeBackend([lambda request: {"issues": []}] * 500)

    with llm.use_backend(fake), caplog.at_level(logging.INFO, logger="clipper.qa"):
        qa.run(QA_VIDEO_ID, tmp_path / "workspace", output_dir, config=_qa_config(tmp_path))

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    progress = [line for line in lines if line.startswith("qa clip")]
    assert len(progress) == 2
    assert any("1/2" in line and line.rstrip().endswith("s") for line in progress)
    assert any("2/2" in line and line.rstrip().endswith("s") for line in progress)


# --------------------------------------------------------------------------
# clipper.download : progression (%, debit).
# --------------------------------------------------------------------------


def _fake_ydl_with_progress(info: dict, events: list[dict]):
    """Comme _make_fake_ydl de test_download.py, mais rejoue ``events`` a
    travers les progress_hooks recus dans les opts avant d'ecrire le fichier
    video (comme le ferait vraiment yt-dlp pendant le telechargement)."""

    class FakeYoutubeDL:
        def __init__(self, opts):
            self._opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def extract_info(self, url, download=True):
            for hook in self._opts.get("progress_hooks", []):
                for event in events:
                    hook(event)
            if download:
                video_path = Path(self._opts["outtmpl"] % {"id": info["id"], "ext": "mp4"})
                video_path.parent.mkdir(parents=True, exist_ok=True)
                video_path.write_bytes(b"fake video bytes")
            return info

    return FakeYoutubeDL


def test_download_logs_progress_percent_and_speed(tmp_path, caplog):
    from clipper.download import download

    info = {"id": "dQw4w9WgXcQ", "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    events = [
        {"status": "downloading", "downloaded_bytes": 0, "total_bytes": 1000, "speed": 100_000.0},
        {"status": "downloading", "downloaded_bytes": 500, "total_bytes": 1000, "speed": 120_000.0},
        {"status": "downloading", "downloaded_bytes": 1000, "total_bytes": 1000, "speed": 130_000.0},
        {"status": "finished"},
    ]
    ydl_factory = _fake_ydl_with_progress(info, events)

    with caplog.at_level(logging.INFO, logger="clipper.download"):
        download(
            f"https://www.youtube.com/watch?v={info['id']}",
            workspace_dir=tmp_path / "workspace", ydl_factory=ydl_factory,
        )

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    progress = [line for line in lines if "telechargement" in line]
    assert progress, "aucune ligne INFO de progression telechargement"
    assert any("50.0%" in line for line in progress)
    assert any("100.0%" in line for line in progress)
    assert any("Mo/s" in line for line in progress)


def test_download_debug_logs_every_progress_event(tmp_path, caplog):
    from clipper.download import download

    info = {"id": "dQw4w9WgXcQ", "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    events = [
        {"status": "downloading", "downloaded_bytes": pct * 10, "total_bytes": 1000, "speed": 100_000.0}
        for pct in range(0, 101, 5)
    ]
    ydl_factory = _fake_ydl_with_progress(info, events)

    with caplog.at_level(logging.DEBUG, logger="clipper.download"):
        download(
            f"https://www.youtube.com/watch?v={info['id']}",
            workspace_dir=tmp_path / "workspace", ydl_factory=ydl_factory,
        )

    debug_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    info_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    debug_progress = [line for line in debug_lines if "telechargement" in line]
    info_progress = [line for line in info_lines if "telechargement" in line]
    assert len(debug_progress) == len(events)
    assert 1 < len(info_progress) < len(events)


# --------------------------------------------------------------------------
# clipper.transcribe : minutes traitees / total, facteur temps reel.
# --------------------------------------------------------------------------

TS_VIDEO_ID = "abcdefghijk"


def _ts_word(word, start, end):
    return SimpleNamespace(word=word, start=start, end=end, probability=0.9)


def _ts_segment(id_, start, end):
    words = [_ts_word(" mot", start, end)]
    return SimpleNamespace(id=id_, start=start, end=end, text="".join(w.word for w in words), words=words)


class _TSFakeWhisperModel:
    def __init__(self, segments, duration):
        self._segments = segments
        self._duration = duration
        self.hf_tokenizer = None

    def transcribe(self, audio, **kwargs):
        info = SimpleNamespace(language="fr", language_probability=0.9, duration=self._duration)
        return iter(self._segments), info


def _ts_model_factory(segments, duration):
    def factory(name, device, compute_type):
        return _TSFakeWhisperModel(segments, duration)

    return factory


def _ts_video_dir(tmp_path: Path) -> Path:
    d = tmp_path / "workspace" / TS_VIDEO_ID
    d.mkdir(parents=True)
    (d / f"{TS_VIDEO_ID}.mp4").write_bytes(b"fake video")
    meta = {"video_id": TS_VIDEO_ID, "title": "t", "description": "d"}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


def test_transcribe_logs_minutes_processed_and_real_time_factor(tmp_path, monkeypatch, caplog):
    import clipper.transcribe as transcribe_module
    from clipper.gpu import Device
    from clipper.transcribe import transcribe

    monkeypatch.setattr(transcribe_module, "get_device", lambda: Device(type="cpu", compute_type="int8"))
    _ts_video_dir(tmp_path)
    duration = 600.0  # 10 minutes
    segments = [_ts_segment(k, k * 60.0, k * 60.0 + 30.0) for k in range(10)]
    config = Config(
        mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={"transcribe": {"vocab": False, "transcript_fix": False}},
    )

    with caplog.at_level(logging.DEBUG, logger="clipper.transcribe"):
        transcribe(
            TS_VIDEO_ID, tmp_path / "workspace", config=config,
            model_factory=_ts_model_factory(segments, duration),
            audio_extractor=lambda video, audio: Path(audio).write_bytes(b"x"),
            pipeline_factory=lambda model: model,
        )

    debug_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    info_lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    debug_progress = [line for line in debug_lines if "facteur temps reel" in line]
    info_progress = [line for line in info_lines if "facteur temps reel" in line]
    assert len(debug_progress) == 10
    assert info_progress, "aucune ligne INFO de progression transcription"
    assert "9.5/10.0 min" in info_progress[-1]


# --------------------------------------------------------------------------
# CLI : -v (INFO) et -vv (DEBUG) ; sans -v, sortie actuelle inchangee (WARNING).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv,expected_level",
    [
        ([], logging.WARNING),
        (["-v"], logging.INFO),
        (["-vv"], logging.DEBUG),
        (["-vvv"], logging.DEBUG),
    ],
)
def test_main_verbosity_flag_sets_the_logging_level(monkeypatch, isolated_cwd, argv, expected_level):
    from clipper.__main__ import main

    captured: dict = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: captured.update(kwargs))

    main([*argv, "status", "no-such-video"])

    assert captured["level"] == expected_level
