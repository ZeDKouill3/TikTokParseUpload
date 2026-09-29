"""Tests de clipper.pipeline et de la CLI (TASK-66a3).

Bout en bout sur une vraie video synthetique (ffmpeg lavfi), avec un faux
yt-dlp, un whisper simule, un detecteur de visages factice et le
FakeBackend de clipper.llm : ni reseau, ni GPU, ni vrai Claude.
"""

from __future__ import annotations

import gc
import json
import logging
import shutil
import subprocess
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper import llm
from clipper.config import Config
from clipper.llm.backend import Usage
from clipper.llm.fake import FakeBackend

ROOT = Path(__file__).resolve().parent.parent
VIDEO_ID = "abcdefghijk"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
DURATION = 80

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
    """Une phrase de 4 mots toutes les 2 s, de 0 a DURATION s."""
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

MOMENT = {"start": 2.0, "end": 72.0}  # 70 s : clip unique (60-120 s, SPEC-1557)


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
    if usage.startswith("jury_"):
        # Mode auto : le jury (clipper.jury) note chaque candidat demande,
        # comme le proposeur, sans veto.
        item = request.schema["properties"]["candidates"]["items"]["properties"]
        candidates = []
        for ref in item["ref"]["enum"]:
            entry = {"ref": ref, "argument": "« GTA six arrive vraiment. » : accroche nette.",
                     "scores": {k: 9 for k in item["scores"]["required"]}}
            if "veto" in item:
                entry.update(veto=False, veto_reason="")
            candidates.append(entry)
        return {"candidates": candidates}
    if usage == "vision":
        n = request.schema["properties"]["frames"]["minItems"]
        return {"frames": [{"index": i, "description": "une mire", "tags": ["mire"], "striking": False}
                           for i in range(n)]}
    if usage == "captions":
        return {"title": "GTA 6 arrive", "caption": "Il arrive vraiment", "hashtags": ["#gta6"],
                "hook_text": "GTA 6 arrive", "screen_title": "GTA 6 confirme \U0001F525"}
    if usage == "emphasis":
        return {"indices": []}
    if usage == "layout":
        return {"layout": "single", "camera": None, "face": None, "reason": "plan unique"}
    if usage == "qa":
        return {"issues": []}
    raise AssertionError(f"usage inattendu {usage!r}")


def backend(*overrides, backend_cls=FakeBackend):
    """FakeBackend qui repond ``answer`` ; ``overrides`` : (usage, reponse)
    consommes une fois, a la premiere requete de cet usage."""
    pending = list(overrides)

    def respond(request):
        for i, (usage, response) in enumerate(pending):
            if usage == request.usage:
                del pending[i]
                return response(request) if callable(response) else response
        return answer(request)

    return backend_cls([respond] * 500)


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
    assert not missing, f"champs SPEC-6127 manquants : {missing}"
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
    # Mode auto : les moments sont choisis par le jury (ADR-ff87).
    assert {c.usage for c in fake.calls if c.usage.startswith("jury_")} == {
        "jury_retention", "jury_spectateur", "jury_monteur", "jury_avocat", "jury_conformite",
    }
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
    pipeline.decide(VIDEO_ID, 0, "adjusted", start=4.0, end=72.0, comment="debut plus net", config=config)
    journal = (tmp_path / "state" / "feedback.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(journal[-1])
    assert entry["video_id"] == VIDEO_ID and entry["decision"] == "adjusted"
    assert entry["moment"]["start"] == 4.0 and entry["moment"]["end"] == 72.0
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
    assert clip["end"] == pytest.approx(72.0, abs=0.2)

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
# TASK-15129acecf26 : journal de consommation LLM (llm_usage.jsonl) branche
# sur le pipeline, y compris les appels faits depuis un thread (subtitles).
# --------------------------------------------------------------------------


class UsageFakeBackend(FakeBackend):
    """FakeBackend qui rapporte une consommation fixe a chaque appel
    (clipper.llm.fake.FakeBackend n'en rapporte aucune : ce n'est pas dans le
    perimetre de cette tache de l'y ajouter)."""

    def complete(self, request):
        text = super().complete(request)
        self.last_usage = Usage(input_tokens=100, output_tokens=20, cost_usd=0.01)
        return text


@no_ffmpeg
def test_pipeline_pass_journals_every_llm_call_including_from_threads_then_summarizes(
    tmp_path, isolated_cwd, source_video, caplog
):
    from clipper import pipeline

    # parallel=1 : l'appel emphase du clip tourne quand meme dans un thread du
    # pool (ThreadPoolExecutor(max_workers=1)), sans le rendre concurrent avec
    # un autre appel sur le meme FakeBackend partage (last_usage n'est pas
    # protege par un verrou).
    config = make_config(tmp_path, mode="auto", subtitles={"parallel": 1})
    fake = backend(backend_cls=UsageFakeBackend)

    with llm.use_backend(fake), caplog.at_level(logging.INFO, logger="clipper.pipeline"):
        state = pipeline.run(URL, config=config, step_options=step_options(source_video))

    assert state["status"] == "done", state
    assert fake.calls, "aucun appel LLM effectue : le test ne prouve rien"

    usage_log_path = tmp_path / "workspace" / VIDEO_ID / "llm_usage.jsonl"
    lines = [json.loads(line) for line in usage_log_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == len(fake.calls)
    usages = [line["usage"] for line in lines]
    # L'etape subtitles appelle le LLM (emphase) depuis un thread du pool :
    # journalise au meme titre que les appels du thread principal.
    assert "emphasis" in usages
    for line in lines:
        assert (line["input_tokens"], line["output_tokens"], line["cost_usd"]) == (100, 20, 0.01)

    # Resume par usage (tokens, cout) journalise a la fin du passage.
    [summary] = [r.getMessage() for r in caplog.records if "consommation LLM par usage" in r.message]
    assert VIDEO_ID in summary
    emphasis_calls = usages.count("emphasis")
    assert "'emphasis'" in summary
    assert f"'calls': {emphasis_calls}" in summary


def test_ask_outside_any_pipeline_pass_writes_nothing_to_a_video_journal(tmp_path, isolated_cwd):
    # ADR-ad2e / criterion TASK-15129acecf26 : le contexte que pipeline pose
    # pour la duree d'un passage ne fuit jamais vers un ask() qui n'en fait
    # pas partie (ici, aucun passage n'a jamais commence).
    with llm.use_backend(FakeBackend([{"issues": []}])):
        llm.ask("qa", "p", [], {"type": "object", "properties": {"issues": {"type": "array"}},
                                "required": ["issues"], "additionalProperties": False})
    assert not (tmp_path / "workspace").exists()


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
# SPEC-6127 : la bande des visages, deduite du recadrage, est donnee a subtitles.
# --------------------------------------------------------------------------


def test_avoid_zones_maps_faces_of_each_reframe_plan_to_output_height():
    from clipper.pipeline import avoid_zones

    def plan(faces, panels, start=0.0, end=10.0):
        return {"start": start, "end": end, "faces": faces, "panels": panels}

    face = {"id": 0, "first": 0.0, "last": 10.0, "box": [800, 100, 1000, 300], "retained": True}
    camera = {"name": "camera", "dest": {"x": 0, "y": 0, "w": 1080, "h": 768},
              "rects": [{"start": 0.0, "end": 10.0, "x": 700, "y": 0, "w": 400, "h": 400}]}
    gameplay = {"name": "gameplay", "dest": {"x": 0, "y": 768, "w": 1080, "h": 1152},
                "rects": [{"start": 0.0, "end": 10.0, "x": 0, "y": 0, "w": 640, "h": 1080}]}
    blur = {**camera, "effect": "blur"}
    later = {**face, "first": 10.0, "last": 20.0}
    camera_later = {**camera, "rects": [{**camera["rects"][0], "start": 10.0, "end": 20.0}]}
    reframe_plan = {"output": {"width": 1080, "height": 1920}, "plans": [
        plan([face], [camera, gameplay]),
        plan([], [camera_later], 10.0, 20.0),
        plan([later], [blur], 20.0, 30.0),
    ]}
    zones = avoid_zones(reframe_plan)
    # Une entree par plan, avec ses bornes ; visage dans la camera (en haut) :
    # y 100..300 sur 400 -> 192..576 px sur 1920.
    assert [(z["start"], z["end"]) for z in zones] == [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)]
    assert [tuple(b) for b in zones[0]["bands"]] == [pytest.approx((0.1, 0.3))]
    # Aucun visage, ou visage seulement sur le fond flou : rien a eviter.
    assert zones[1]["bands"] == [] and zones[2]["bands"] == []
    # Visage hors de tout panneau.
    outside = {**face, "box": [1500, 900, 1600, 1000]}
    assert avoid_zones({**reframe_plan, "plans": [plan([outside], [camera, gameplay])]})[0]["bands"] == []


def test_avoid_zones_keeps_separate_faces_as_separate_bands():
    """Deux visages (haut et bas d'un ecran partage) : deux bandes, pas une
    seule bande du haut du premier au bas du second."""
    from clipper.pipeline import avoid_zones

    top = {"name": "top", "dest": {"x": 0, "y": 0, "w": 1080, "h": 960},
           "rects": [{"start": 0.0, "end": 5.0, "x": 0, "y": 0, "w": 1215, "h": 1080}]}
    bottom = {"name": "bottom", "dest": {"x": 0, "y": 960, "w": 1080, "h": 960},
              "rects": [{"start": 0.0, "end": 5.0, "x": 1000, "y": 0, "w": 1215, "h": 1080}]}
    a = {"id": 0, "first": 0.0, "last": 5.0, "box": [100, 108, 300, 324], "retained": True}    # dans top seulement
    b = {"id": 1, "first": 0.0, "last": 5.0, "box": [1500, 756, 1700, 972], "retained": True}  # dans bottom seulement
    reframe_plan = {"output": {"width": 1080, "height": 1920},
                    "plans": [{"start": 0.0, "end": 5.0, "faces": [a, b], "panels": [top, bottom]}]}
    bands = sorted(tuple(x) for x in avoid_zones(reframe_plan)[0]["bands"])
    # a : 108..324 * 960/1080 -> 96..288 px ; b : 960 + 672..864 -> 1632..1824 px
    assert bands == [pytest.approx((0.05, 0.15)), pytest.approx((0.85, 0.95))]


def test_avoid_zones_ignores_faces_not_retained_by_the_reframe_plan():
    """Un visage detecte mais non retenu (retained: False - main, sac, torse,
    ecran) ne doit pas bloquer de place pour les sous-titres."""
    from clipper.pipeline import avoid_zones

    camera = {"name": "camera", "dest": {"x": 0, "y": 0, "w": 1080, "h": 768},
              "rects": [{"start": 0.0, "end": 10.0, "x": 700, "y": 0, "w": 400, "h": 400}]}
    not_retained = {"id": 0, "first": 0.0, "last": 10.0, "box": [800, 100, 1000, 300], "retained": False}
    reframe_plan = {"output": {"width": 1080, "height": 1920}, "plans": [
        {"start": 0.0, "end": 10.0, "faces": [not_retained], "panels": [camera]},
    ]}
    assert avoid_zones(reframe_plan)[0]["bands"] == []


def test_avoid_zones_raises_on_a_face_without_a_retained_field():
    """Plan de recadrage d'ancien format (sans 'retained') : erreur explicite,
    jamais une supposition silencieuse (ADR-ad2e)."""
    from clipper.pipeline import PipelineError, avoid_zones

    camera = {"name": "camera", "dest": {"x": 0, "y": 0, "w": 1080, "h": 768},
              "rects": [{"start": 0.0, "end": 10.0, "x": 700, "y": 0, "w": 400, "h": 400}]}
    face = {"id": 0, "first": 0.0, "last": 10.0, "box": [800, 100, 1000, 300]}
    reframe_plan = {"output": {"width": 1080, "height": 1920}, "plans": [
        {"start": 0.0, "end": 10.0, "faces": [face], "panels": [camera]},
    ]}
    with pytest.raises(PipelineError, match="retained"):
        avoid_zones(reframe_plan)


# --------------------------------------------------------------------------
# SPEC-6127 (TASK-a62e) : en letterbox, subtitles recoit text_zones.subtitles
# de la racine du plan de recadrage.
# --------------------------------------------------------------------------


def letterbox_workspace(tmp_path, text_zones):
    """captions.json, transcript.json et reframe/00.json (plan letterbox du
    contrat commun) pour un clip 00 de 0 a 4 s."""
    d = tmp_path / "workspace" / VIDEO_ID
    (d / "reframe").mkdir(parents=True)
    words = [{"word": f" {w}", "start": 0.5 * k, "end": 0.5 * (k + 1), "probability": 0.9}
             for k, w in enumerate(["GTA", "six", "arrive", "vraiment."])]
    (d / "transcript.json").write_text(json.dumps({"video_id": VIDEO_ID, "language": "fr", "segments": [
        {"id": 0, "start": 0.0, "end": 2.0, "text": "", "words": words}]}), encoding="utf-8")
    (d / "captions.json").write_text(json.dumps({"clips": [{"id": "00", "start": 0.0, "end": 4.0}]}),
                                     encoding="utf-8")
    plan = {"layout": "letterbox", "format": "letterbox", "output": {"width": 1080, "height": 1920},
            "plans": [{"index": 0, "start": 0.0, "end": 4.0, "image": None, "llm": None,
                       "layout": "letterbox", "reason": None, "faces": [], "panels": []}]}
    if text_zones is not None:
        plan["text_zones"] = text_zones
    (d / "reframe" / "00.json").write_text(json.dumps(plan), encoding="utf-8")
    return d


def run_subtitles_step(tmp_path):
    from clipper import pipeline

    config = Config(mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")
    run = pipeline._Run(pipeline.new_state(VIDEO_ID, URL, "auto"), config, False, None)
    with llm.use_backend(FakeBackend([{"indices": []}])):
        run.subtitles()


def test_letterbox_plan_gives_its_subtitles_text_zone_to_subtitles(tmp_path):
    zone = {"x0": 200, "y0": 1300, "x1": 880, "y1": 1500}
    d = letterbox_workspace(tmp_path, {"title": {"x0": 150, "y0": 160, "x1": 930, "y1": 424},
                                       "subtitles": zone,
                                       "part": {"x0": 150, "y0": 1464, "x1": 930, "y1": 1520}})
    run_subtitles_step(tmp_path)
    ass = (d / "subtitles" / "00.ass").read_text(encoding="utf-8")
    assert ass.startswith("; format: letterbox")
    events = [line.split(",", 9) for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert events
    from clipper.subtitles import CONFIG_DEFAULTS as SUBTITLES_DEFAULTS

    offset = SUBTITLES_DEFAULTS["letterbox_offset_y"]
    for ev in events:
        # MarginL = x0, MarginR = 1080 - x1, MarginV = y0 + letterbox_offset_y (+ pas pour une 2e ligne)
        assert (int(ev[5]), int(ev[6])) == (200, 1080 - 880)
        assert int(ev[7]) in (1300 + offset, 1300 + offset + 78)


@pytest.mark.parametrize("text_zones", [None, {"title": {"x0": 150, "y0": 160, "x1": 930, "y1": 424}}])
def test_letterbox_plan_without_a_subtitles_zone_is_an_error(tmp_path, text_zones):
    from clipper.pipeline import PipelineError

    d = letterbox_workspace(tmp_path, text_zones)
    with pytest.raises(PipelineError, match="text_zones"):
        run_subtitles_step(tmp_path)
    assert not (d / "subtitles" / "00.ass").exists()


def test_stream_plan_gives_its_subtitles_text_zone_to_subtitles(tmp_path):
    # SPEC-3a88 (TASK-9e0c) : un plan stream passe sa zone sous-titres comme letterbox
    zone = {"x0": 150, "y0": 1224, "x1": 930, "y1": 1448}
    d = letterbox_workspace(tmp_path, {"title": {"x0": 150, "y0": 160, "x1": 930, "y1": 424},
                                       "subtitles": zone,
                                       "part": {"x0": 150, "y0": 1464, "x1": 930, "y1": 1520}})
    plan = json.loads((d / "reframe" / "00.json").read_text(encoding="utf-8"))
    plan["layout"] = plan["plans"][0]["layout"] = "stream"
    (d / "reframe" / "00.json").write_text(json.dumps(plan), encoding="utf-8")
    run_subtitles_step(tmp_path)
    ass = (d / "subtitles" / "00.ass").read_text(encoding="utf-8")
    assert ass.startswith("; format: letterbox")
    events = [line.split(",", 9) for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert events
    from clipper.subtitles import CONFIG_DEFAULTS as SUBTITLES_DEFAULTS

    offset = SUBTITLES_DEFAULTS["letterbox_offset_y"]
    for ev in events:
        assert (int(ev[5]), int(ev[6])) == (150, 1080 - 930)
        assert int(ev[7]) in (1224 + offset, 1224 + offset + 78)


def test_reframe_step_detects_the_facecam_once_per_video_in_stream_auto(tmp_path, monkeypatch):
    from clipper import pipeline, reframe

    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / "captions.json").write_text(json.dumps({"clips": [
        {"id": "00", "start": 0.0, "end": 4.0}, {"id": "01", "start": 4.0, "end": 8.0}]}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(reframe, "detect_facecam", lambda *a, **k: calls.append(("facecam", a, k)))
    monkeypatch.setattr(reframe, "reframe", lambda *a, **k: calls.append(("clip", a[1], k["force"])))

    for layout, expected in (("letterbox", 0), ("stream_auto", 1)):
        calls.clear()
        config = Config(mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
                        _sections={"reframe": {"layout": layout}})
        run = pipeline._Run(pipeline.new_state(VIDEO_ID, URL, "auto"), config, True, None)
        run.reframe()
        assert [c[0] for c in calls] == ["facecam"] * expected + ["clip", "clip"]
        if expected:
            assert calls[0][1][0] == VIDEO_ID and calls[0][2]["force"] is True


def test_hook_zones_reserve_the_hook_band_for_the_hook_duration(tmp_path):
    from clipper.pipeline import hook_zones

    clip = {"id": "00", "start": 683.3, "end": 726.0}
    [zone] = hook_zones(clip, make_config(tmp_path))
    # render dessine l'accroche a y=100 px, police 64, les 2 premieres secondes
    assert (zone["start"], zone["end"]) == pytest.approx((683.3, 685.3))
    [(top, bottom)] = zone["bands"]
    assert top * 1920 <= 100 and bottom * 1920 >= 164

    config = make_config(tmp_path, render={"hook_margin_top": 300, "hook_font_size": 80, "hook_seconds": 3.0})
    [zone] = hook_zones(clip, config)
    assert zone["end"] == pytest.approx(686.3)
    [(top, bottom)] = zone["bands"]
    assert top * 1920 <= 300 and bottom * 1920 >= 380 and bottom * 1920 < 500


# --------------------------------------------------------------------------
# TASK-ce6e : l'etape subtitles genere les clips en parallele, au plus
# ``parallel`` a la fois (CONFIG_DEFAULTS de subtitles).
# --------------------------------------------------------------------------

N_CLIPS = 6
CROP_CLIP = "01"  # un clip recadre (zones a eviter + accroche), les autres letterbox


def parallel_workspace(tmp_path, fail_clip=None):
    """captions.json, transcript.json et reframe/<id>.json pour N_CLIPS clips
    de 4 s, clip k de 4k a 4k + 4 ; les mots du clip ``fail_clip`` contiennent
    ``echec``."""
    d = tmp_path / "workspace" / VIDEO_ID
    (d / "reframe").mkdir(parents=True)
    words, clips = [], []
    for k in range(N_CLIPS):
        clip_id = f"{k:02d}"
        texts = ["echec"] * 4 if clip_id == fail_clip else [f"mot{k}{c}" for c in "abcd"]
        words += [{"word": f" {w}", "start": 4 * k + 0.5 * j + 0.2, "end": 4 * k + 0.5 * j + 0.6,
                   "probability": 0.9} for j, w in enumerate(texts)]
        clips.append({"id": clip_id, "start": 4.0 * k, "end": 4.0 * k + 4})
        plan = {"output": {"width": 1080, "height": 1920},
                "plans": [{"index": 0, "start": 4.0 * k, "end": 4.0 * k + 4, "faces": [], "panels": []}]}
        if clip_id != CROP_CLIP:
            plan.update(layout="letterbox", format="letterbox",
                        text_zones={"subtitles": {"x0": 150, "y0": 1400, "x1": 930, "y1": 1700}})
        (d / "reframe" / f"{clip_id}.json").write_text(json.dumps(plan), encoding="utf-8")
    (d / "transcript.json").write_text(json.dumps({"video_id": VIDEO_ID, "language": "fr", "segments": [
        {"id": 0, "start": 0.0, "end": 4.0 * N_CLIPS, "text": "", "words": words}]}), encoding="utf-8")
    (d / "captions.json").write_text(json.dumps({"clips": clips}), encoding="utf-8")
    return d


class ConcurrentEmphasis:
    """Reponse d'emphase qui compte les appels simultanes (pic dans ``peak``)
    et echoue pour un clip dont les mots contiennent ``echec``."""

    def __init__(self):
        import threading

        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def __call__(self, request):
        import time

        assert request.usage == "emphasis"
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.1)
            if "echec" in request.prompt:
                return llm.LLMError("reponse refusee pour le clip en echec")
            return {"indices": [0, 2]}
        finally:
            with self.lock:
                self.active -= 1


def run_parallel_subtitles(tmp_path, parallel, emphasis=None):
    from clipper import pipeline

    config = Config(mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
                    _sections={"subtitles": {"parallel": parallel}})
    run = pipeline._Run(pipeline.new_state(VIDEO_ID, URL, "auto"), config, False, None)
    emphasis = emphasis or ConcurrentEmphasis()
    with llm.use_backend(FakeBackend([emphasis] * 500)):
        run.subtitles()
    return emphasis


def test_subtitles_parallel_defaults_to_4():
    from clipper.subtitles import CONFIG_DEFAULTS as SUBTITLES_DEFAULTS

    assert SUBTITLES_DEFAULTS["parallel"] == 4


def test_subtitles_step_overlaps_emphasis_calls_with_parallel_4(tmp_path):
    parallel_workspace(tmp_path)
    emphasis = run_parallel_subtitles(tmp_path, 4)
    assert emphasis.peak >= 2
    assert emphasis.peak <= 4


def test_subtitles_step_never_overlaps_with_parallel_1(tmp_path):
    parallel_workspace(tmp_path)
    emphasis = run_parallel_subtitles(tmp_path, 1)
    assert emphasis.peak == 1


def test_subtitles_files_are_identical_with_parallel_1_and_4(tmp_path):
    files = {}
    for parallel in (1, 4):
        d = parallel_workspace(tmp_path / f"p{parallel}")
        run_parallel_subtitles(tmp_path / f"p{parallel}", parallel)
        files[parallel] = {p.name: p.read_bytes() for p in sorted((d / "subtitles").glob("*.ass"))}
    assert sorted(files[1]) == [f"{k:02d}.ass" for k in range(N_CLIPS)]
    assert files[1] == files[4]
    # zones calculees clip par clip : letterbox pour tous sauf le clip recadre
    assert files[4]["00.ass"].startswith(b"; format: letterbox")
    assert not files[4][f"{CROP_CLIP}.ass"].startswith(b"; format: letterbox")


def test_a_failing_clip_fails_the_step_after_the_other_clips_are_written(tmp_path):
    d = parallel_workspace(tmp_path, fail_clip="03")
    with pytest.raises(llm.LLMError, match="clip en echec"):
        run_parallel_subtitles(tmp_path, 4)
    written = sorted(p.name for p in (d / "subtitles").glob("*.ass"))
    assert written == [f"{k:02d}.ass" for k in range(N_CLIPS) if k != 3]


def test_a_rerun_after_a_failure_skips_the_clips_already_written(tmp_path):
    d = parallel_workspace(tmp_path, fail_clip="03")
    with pytest.raises(llm.LLMError):
        run_parallel_subtitles(tmp_path, 4)
    before = {p.name: p.stat().st_mtime_ns for p in (d / "subtitles").glob("*.ass")}
    emphasis = ConcurrentEmphasis()
    with pytest.raises(llm.LLMError):
        run_parallel_subtitles(tmp_path, 4, emphasis)
    after = {p.name: p.stat().st_mtime_ns for p in (d / "subtitles").glob("*.ass")}
    assert after == before
    assert emphasis.peak == 1  # seul le clip en echec rappelle le LLM


@pytest.mark.parametrize("parallel", [0, -2])
def test_subtitles_parallel_below_1_is_refused(tmp_path, parallel):
    from clipper.pipeline import PipelineError

    d = parallel_workspace(tmp_path)
    with pytest.raises(PipelineError, match="parallel"):
        run_parallel_subtitles(tmp_path, parallel)
    assert not (d / "subtitles").exists()
