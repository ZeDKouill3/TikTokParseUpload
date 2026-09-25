"""Tests de clipper.pipeline et de la CLI (TASK-66a3).

Bout en bout sur une vraie video synthetique (ffmpeg lavfi), avec un faux
yt-dlp, un whisper simule, un detecteur de visages factice et le
FakeBackend de clipper.llm : ni reseau, ni GPU, ni vrai Claude.
"""

from __future__ import annotations

import gc
import json
import shutil
import subprocess
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper import llm
from clipper.config import Config
from clipper.llm.fake import FakeBackend

ROOT = Path(__file__).resolve().parent.parent
VIDEO_ID = "abcdefghijk"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
DURATION = 30

no_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe absents du PATH",
)

SPEC_FIELDS = (
    "video_id", "source_url", "source_title", "clip_id", "part", "parts_total", "start", "end",
    "duration", "language", "score", "scores", "reason", "hook_text", "title", "caption",
    "hashtags", "transcript", "layout", "qa", "created_at",
)


# --------------------------------------------------------------------------
# Video synthetique, faux yt-dlp, whisper simule, detecteur factice.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def source_video(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg absent du PATH")
    path = tmp_path_factory.mktemp("src") / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={DURATION}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={DURATION}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path


def fake_ydl(source: Path):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            target = Path(self.opts["outtmpl"] % {"id": VIDEO_ID, "ext": "mp4"})
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            return {"id": VIDEO_ID, "title": "GTA 6 : le trailer", "description": "Rockstar et Vice City",
                    "duration": DURATION}

    return FakeYoutubeDL


def _segments():
    """Une phrase de 4 mots toutes les 2 s, de 0 a 30 s."""
    segments = []
    for i in range(DURATION // 2):
        t = 2.0 * i
        words = [SimpleNamespace(word=f" {w}", start=t + 0.5 * k, end=t + 0.5 * (k + 1), probability=0.9)
                 for k, w in enumerate(["GTA", "six", "arrive", "vraiment."])]
        segments.append(SimpleNamespace(id=i, start=t, end=t + 2.0, text="".join(w.word for w in words),
                                        words=words))
    return segments


class WhisperFactory:
    """Whisper simule ; ne garde qu'une weakref vers le modele pour savoir
    s'il a ete libere (ADR-fb9b)."""

    def __init__(self, fail=False):
        self.fail = fail
        self.built = 0
        self.ref = None

    def __call__(self, name, device, compute_type):
        assert not self.fail, "whisper recharge alors que la transcription existe"
        self.built += 1
        segments = _segments()

        class Model:
            def transcribe(self, audio, **kwargs):
                info = SimpleNamespace(language="fr", language_probability=0.99, duration=float(DURATION))
                return iter(segments), info

        model = Model()
        self.ref = weakref.ref(model)
        return model

    def alive(self):
        gc.collect()
        return self.ref is not None and self.ref() is not None


def fake_audio_extractor(video_path, audio_path):
    Path(audio_path).write_bytes(b"RIFF")


class DetectorFactory:
    """Aucun visage ; verifie a la construction que whisper est deja libere
    (un seul modele lourd en VRAM, ADR-fb9b)."""

    def __init__(self, whisper):
        self.whisper = whisper
        self.built = 0

    def __call__(self, settings, device):
        assert not self.whisper.alive(), "detecteur de visages charge alors que whisper est en memoire"
        self.built += 1

        class Detector:
            def detect(self, frame):
                return []

            def close(self):
                pass

        return Detector()


def step_options(source, whisper=None):
    whisper = whisper or WhisperFactory()
    return {
        "download": {"ydl_factory": fake_ydl(source)},
        "transcribe": {"model_factory": whisper, "audio_extractor": fake_audio_extractor},
        "reframe": {"detector_factory": DetectorFactory(whisper)},
    }


# --------------------------------------------------------------------------
# Faux LLM : une reponse valide par usage.
# --------------------------------------------------------------------------

MOMENT = {"start": 2.0, "end": 26.0}


def answer(request):
    usage = request.usage
    if usage == "vocab":
        return {"words": ["Rockstar"]}
    if usage == "transcript_fix":
        return {"corrections": []}
    if usage == "moments":
        scores = {k: 9 for k in ("hook", "standalone", "payoff", "emotion", "value", "trend")}
        return {"moments": [{"hook_text": "GTA six arrive vraiment.", "start": MOMENT["start"],
                             "end": MOMENT["end"], "format": "single", "part_breaks": [],
                             "justification": "Annonce forte", "scores": scores}]}
    if usage == "vision":
        n = request.schema["properties"]["frames"]["minItems"]
        return {"frames": [{"index": i, "description": "une mire", "tags": ["mire"], "striking": False}
                           for i in range(n)]}
    if usage == "captions":
        return {"title": "GTA 6 arrive", "caption": "Il arrive vraiment", "hashtags": ["#gta6"],
                "hook_text": "GTA 6 arrive"}
    if usage == "emphasis":
        return {"indices": []}
    if usage == "layout":
        return {"layout": "single", "camera": None, "face": None, "reason": "plan unique"}
    if usage == "qa":
        return {"issues": []}
    raise AssertionError(f"usage inattendu {usage!r}")


def backend(*overrides):
    """FakeBackend qui repond ``answer`` ; ``overrides`` : (usage, reponse)
    consommes une fois, a la premiere requete de cet usage."""
    pending = list(overrides)

    def respond(request):
        for i, (usage, response) in enumerate(pending):
            if usage == request.usage:
                del pending[i]
                return response(request) if callable(response) else response
        return answer(request)

    return FakeBackend([respond] * 500)


def make_config(tmp_path, mode="auto", **sections):
    rubric = tmp_path / "rubric.toml"
    if not rubric.exists():
        shutil.copyfile(ROOT / "rubric.toml", rubric)
    base = {
        "moments": {"rubric_path": str(rubric)},
        "parts": {"rubric_path": str(rubric)},
        "feedback": {"journal_path": str(tmp_path / "state" / "feedback.jsonl")},
        "render": {"x264_preset": "ultrafast"},
    }
    for name, table in sections.items():
        base[name] = {**base.get(name, {}), **table}
    return Config(mode=mode, workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
                  _sections=base)


def clip_files(tmp_path):
    out = tmp_path / "output" / VIDEO_ID
    return sorted(out.glob("*.mp4")), sorted(out.glob("*.json"))


def assert_valid_clip(json_path):
    from clipper import qa

    clip = json.loads(json_path.read_text(encoding="utf-8"))
    missing = [f for f in SPEC_FIELDS if f not in clip]
    assert not missing, f"champs SPEC-350f manquants : {missing}"
    assert clip["video_id"] == VIDEO_ID
    assert clip["qa"]["status"] == "passed"
    assert qa.is_ready(clip)
    assert json_path.with_suffix(".mp4").stat().st_size > 0
    return clip


PRE_REVIEW = ("download", "transcribe", "scenes", "audio", "moments", "vision", "parts")
POST_REVIEW = ("captions", "reframe", "subtitles", "render", "qa")


# --------------------------------------------------------------------------
# C1, C5, C7 : mode auto de bout en bout, file d'attente sur erreur transitoire.
# C2 : relance sans rien refaire.
# --------------------------------------------------------------------------


@no_ffmpeg
def test_auto_runs_every_step_queues_a_transient_error_then_finishes(tmp_path, isolated_cwd, source_video):
    from clipper import pipeline

    config = make_config(tmp_path, mode="auto", pipeline={"retry_delays": [600]})
    whisper = WhisperFactory()
    opts = step_options(source_video, whisper)
    t0 = datetime.now(timezone.utc)

    fake = backend(("qa", llm.TransientLLMError("quota atteint")))
    with llm.use_backend(fake):
        state = pipeline.run(URL, config=config, step_options=opts)

    # Erreur transitoire a l'etape qa : la video part en file d'attente.
    assert state["status"] == "queued"
    assert "quota atteint" in state["reason"]
    assert state["steps"]["qa"]["status"] == "failed"
    assert "quota atteint" in state["steps"]["qa"]["reason"]
    for name in PRE_REVIEW + ("captions", "reframe", "subtitles", "render"):
        assert state["steps"][name]["status"] == "done", name
    retry_at = datetime.fromisoformat(state["retry_at"])
    assert retry_at >= t0 + timedelta(seconds=600)
    assert pipeline.load_state(VIDEO_ID, config=config) == state

    # Pas encore l'heure : rien ne bouge.
    with llm.use_backend(FakeBackend([])):
        assert pipeline.process_queue(config=config, now=t0, step_options=opts) == []
    assert pipeline.load_state(VIDEO_ID, config=config)["status"] == "queued"

    # Apres le delai : reprise, seule l'etape qa refait un appel LLM.
    fake = backend()
    with llm.use_backend(fake):
        done = pipeline.process_queue(config=config, now=retry_at + timedelta(seconds=1), step_options=opts)
    assert [s["video_id"] for s in done] == [VIDEO_ID]
    state = pipeline.load_state(VIDEO_ID, config=config)
    assert state["status"] == "done", state
    assert state["retry_at"] is None
    assert {c.usage for c in fake.calls} == {"qa"}
    assert all(state["steps"][n]["status"] == "done" for n in PRE_REVIEW + POST_REVIEW)
    assert whisper.built == 1

    mp4s, jsons = clip_files(tmp_path)
    assert len(mp4s) >= 1 and len(jsons) == len(mp4s)
    clip = assert_valid_clip(jsons[0])
    assert state["clips"] == [
        {"clip_id": clip["clip_id"], "ready": True, "qa_status": "passed", "issues": [],
         "mp4": str(jsons[0].with_suffix(".mp4")), "json": str(jsons[0])}
    ]

    # Relance : tout est deja fait, aucun appel LLM, whisper jamais recharge.
    opts2 = step_options(source_video, WhisperFactory(fail=True))
    with llm.use_backend(FakeBackend([])):
        again = pipeline.run(URL, config=config, step_options=opts2)
    assert again["status"] == "done"
    assert again["clips"] == state["clips"]


# --------------------------------------------------------------------------
# C3, C4 : mode review, arret apres moments et parts, reprise par render.
# --------------------------------------------------------------------------


@no_ffmpeg
def test_review_stops_for_decisions_then_render_resumes(tmp_path, isolated_cwd, source_video):
    from clipper import pipeline

    config = make_config(tmp_path, mode="review")
    opts = step_options(source_video)

    fake = backend()
    with llm.use_backend(fake):
        state = pipeline.run(URL, config=config, step_options=opts)

    assert state["status"] == "awaiting_review"
    for name in PRE_REVIEW:
        assert state["steps"][name]["status"] == "done", name
    for name in POST_REVIEW:
        assert state["steps"][name]["status"] == "pending", name
    assert state["awaiting"] == [0]
    assert clip_files(tmp_path) == ([], [])
    assert not {"captions", "layout", "qa", "emphasis"} & {c.usage for c in fake.calls}

    # Sans decision, pas de rendu (ADR-ad2e).
    with llm.use_backend(FakeBackend([])):
        with pytest.raises(pipeline.PipelineError, match="0"):
            pipeline.render(VIDEO_ID, config=config, step_options=opts)
    assert clip_files(tmp_path) == ([], [])

    # Decision humaine journalisee via feedback, bornes ajustees.
    pipeline.decide(VIDEO_ID, 0, "adjusted", start=4.0, end=26.0, comment="debut plus net", config=config)
    journal = (tmp_path / "state" / "feedback.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(journal[-1])
    assert entry["video_id"] == VIDEO_ID and entry["decision"] == "adjusted"
    assert entry["moment"]["start"] == 4.0 and entry["moment"]["end"] == 26.0
    assert entry["commentaire"] == "debut plus net"
    assert "GTA six arrive" in entry["texte_moment"]

    with llm.use_backend(backend()):
        state = pipeline.render(VIDEO_ID, config=config, step_options=opts)
    assert state["status"] == "done", state
    assert all(state["steps"][n]["status"] == "done" for n in PRE_REVIEW + POST_REVIEW)

    _, jsons = clip_files(tmp_path)
    assert len(jsons) == 1
    clip = assert_valid_clip(jsons[0])
    assert clip["start"] == pytest.approx(4.0, abs=0.2)
    assert clip["end"] == pytest.approx(26.0, abs=0.2)

    # Relancer run sur la video terminee ne la remet pas en revue.
    with llm.use_backend(FakeBackend([])):
        again = pipeline.run(URL, config=config, step_options=step_options(source_video, WhisperFactory(fail=True)))
    assert again["status"] == "done"
    assert again["clips"] == state["clips"]


@no_ffmpeg
def test_review_rejected_moment_is_never_rendered(tmp_path, isolated_cwd, source_video):
    from clipper import pipeline

    config = make_config(tmp_path, mode="review")
    opts = step_options(source_video)
    with llm.use_backend(backend()):
        pipeline.run(URL, config=config, step_options=opts)

    pipeline.decide(VIDEO_ID, 0, "rejected", config=config)
    fake = backend()
    with llm.use_backend(fake):
        state = pipeline.render(VIDEO_ID, config=config, step_options=opts)

    assert state["status"] == "done"
    assert state["clips"] == []
    assert clip_files(tmp_path) == ([], [])
    assert fake.calls == []


def test_decide_refuses_an_unknown_moment_or_decision(tmp_path, isolated_cwd):
    from clipper import pipeline

    config = make_config(tmp_path, mode="review")
    video_dir = tmp_path / "workspace" / VIDEO_ID
    video_dir.mkdir(parents=True)
    (video_dir / "parts.json").write_text(json.dumps({"video_id": VIDEO_ID, "moments": [], "rejected": []}))
    (video_dir / "moments.json").write_text(json.dumps({"video_id": VIDEO_ID, "moments": [], "rejected": []}))

    with pytest.raises(pipeline.PipelineError, match="7"):
        pipeline.decide(VIDEO_ID, 7, "accepted", config=config)
    with pytest.raises(pipeline.PipelineError, match="adjusted"):
        pipeline.decide(VIDEO_ID, 0, "adjusted", config=config)
    assert not (tmp_path / "state" / "feedback.jsonl").exists()


# --------------------------------------------------------------------------
# C5 : echec definitif, plafond de re-essais ; C6 : etat running lisible.
# --------------------------------------------------------------------------


@no_ffmpeg
def test_permanent_error_fails_with_reason_and_is_not_queued(tmp_path, isolated_cwd, source_video):
    from clipper import pipeline

    config = make_config(tmp_path, mode="auto")
    with llm.use_backend(backend(("moments", llm.LLMError("binaire claude introuvable")))):
        state = pipeline.run(URL, config=config, step_options=step_options(source_video))

    assert state["status"] == "failed"
    assert "binaire claude introuvable" in state["reason"]
    assert state["retry_at"] is None
    assert state["steps"]["moments"]["status"] == "failed"
    assert "binaire claude introuvable" in state["steps"]["moments"]["reason"]
    assert state["steps"]["parts"]["status"] == "pending"
    assert not (tmp_path / "workspace" / VIDEO_ID / "moments.json").exists()

    with llm.use_backend(FakeBackend([])):
        assert pipeline.process_queue(config=config, now=datetime.now(timezone.utc) + timedelta(days=1)) == []


@no_ffmpeg
def test_transient_error_beyond_max_attempts_fails(tmp_path, isolated_cwd, source_video):
    from clipper import pipeline

    config = make_config(tmp_path, mode="auto", pipeline={"max_attempts": 1})
    with llm.use_backend(backend(("moments", llm.TransientLLMError("reseau coupe")))):
        state = pipeline.run(URL, config=config, step_options=step_options(source_video))

    assert state["status"] == "failed"
    assert "reseau coupe" in state["reason"]
    assert state["retry_at"] is None


@no_ffmpeg
def test_step_state_is_running_while_the_step_works(tmp_path, isolated_cwd, source_video):
    from clipper import pipeline

    config = make_config(tmp_path, mode="review")
    seen = {}

    def spy(request):
        state = pipeline.load_state(VIDEO_ID, config=config)
        seen["moments"] = state["steps"]["moments"]["status"]
        seen["audio"] = state["steps"]["audio"]["status"]
        seen["parts"] = state["steps"]["parts"]["status"]
        seen["video"] = state["status"]
        return answer(request)

    with llm.use_backend(backend(("moments", spy))):
        pipeline.run(URL, config=config, step_options=step_options(source_video))

    assert seen == {"moments": "running", "audio": "done", "parts": "pending", "video": "running"}


@no_ffmpeg
def test_moments_gets_feedback_examples_and_is_rescored_after_vision_without_llm(tmp_path, isolated_cwd,
                                                                                source_video):
    from clipper import feedback, pipeline

    config = make_config(tmp_path, mode="review")
    feedback.record("zzzzzzzzzzz", {"start": 1.0, "end": 30.0}, "accepted", "Exemple passe tres distinctif",
                    path=tmp_path / "state" / "feedback.jsonl")

    def no_moments_after_vision(request):
        if request.usage == "moments" and any(c.usage == "vision" for c in fake.calls):
            raise AssertionError("moments redemande au LLM apres vision")
        return answer(request)

    fake = FakeBackend([no_moments_after_vision] * 500)
    with llm.use_backend(fake):
        state = pipeline.run(URL, config=config, step_options=step_options(source_video))

    assert state["status"] == "awaiting_review", state["reason"]
    usages = [c.usage for c in fake.calls]
    assert usages.count("moments") == 1
    assert usages.index("moments") < usages.index("vision")
    [moments_prompt] = [c.prompt for c in fake.calls if c.usage == "moments"]
    assert "Exemple passe tres distinctif" in moments_prompt
    video_dir = tmp_path / "workspace" / VIDEO_ID
    data = json.loads((video_dir / "moments.json").read_text(encoding="utf-8"))
    assert "rescored" in data, "moments non re-note apres vision"
    assert (video_dir / "moments.json").stat().st_mtime_ns >= (video_dir / "vision.json").stat().st_mtime_ns


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_status_prints_the_state_as_json(tmp_path, isolated_cwd, capsys):
    from clipper import pipeline
    from clipper.__main__ import main

    (isolated_cwd / "config.toml").write_text('workspace_dir = "ws"\n', encoding="utf-8")
    config = Config(mode="review", workspace_dir=Path("ws"), output_dir=Path("output"))
    pipeline.save_state(pipeline.new_state(VIDEO_ID, URL, "review"), config=config)

    assert main(["status", VIDEO_ID]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["video_id"] == VIDEO_ID
    assert state["steps"]["download"] == {"status": "pending", "reason": None, "started_at": None,
                                          "finished_at": None}


def test_cli_run_and_render_go_through_the_pipeline(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline
    from clipper.__main__ import main

    calls = []
    monkeypatch.setattr(pipeline, "run", lambda url, **kw: calls.append(("run", url, kw["force"])) or {"status": "awaiting_review"})
    monkeypatch.setattr(pipeline, "render", lambda vid, **kw: calls.append(("render", vid, kw["force"])) or {"status": "queued"})

    assert main(["run", URL]) == 0
    assert main(["render", VIDEO_ID, "--force"]) == pipeline.EXIT_QUEUED
    assert calls == [("run", URL, False), ("render", VIDEO_ID, True)]


def test_cli_unknown_video_status_is_an_error(tmp_path, isolated_cwd, capsys):
    from clipper.__main__ import main

    assert main(["status", "inconnu0000"]) == 1
    assert "inconnu0000" in capsys.readouterr().err


# --------------------------------------------------------------------------
# SPEC-350f : la bande des visages, deduite du recadrage, est donnee a subtitles.
# --------------------------------------------------------------------------


def test_avoid_zone_maps_faces_of_the_reframe_plan_to_output_height():
    from clipper.pipeline import avoid_zone

    def plan(faces, panels):
        return {"output": {"width": 1080, "height": 1920},
                "plans": [{"start": 0.0, "end": 10.0, "faces": faces, "panels": panels}]}

    face = {"id": 0, "first": 0.0, "last": 10.0, "box": [800, 100, 1000, 300]}
    camera = {"name": "camera", "dest": {"x": 0, "y": 0, "w": 1080, "h": 768},
              "rects": [{"start": 0.0, "end": 10.0, "x": 700, "y": 0, "w": 400, "h": 400}]}
    gameplay = {"name": "gameplay", "dest": {"x": 0, "y": 768, "w": 1080, "h": 1152},
                "rects": [{"start": 0.0, "end": 10.0, "x": 0, "y": 0, "w": 640, "h": 1080}]}
    # Visage dans la camera (en haut) : y 100..300 sur 400 -> 192..576 px sur 1920.
    assert avoid_zone(plan([face], [camera, gameplay])) == pytest.approx((0.1, 0.3))
    # Aucun visage, ou visage hors de tout panneau : rien a eviter.
    assert avoid_zone(plan([], [camera, gameplay])) is None
    assert avoid_zone(plan([{**face, "box": [1500, 900, 1600, 1000]}], [camera, gameplay])) is None
    # Le fond flou ne compte pas.
    blur = {**camera, "effect": "blur"}
    assert avoid_zone(plan([face], [blur])) is None
