"""Test de fumee reel (TASK-8bf6) : un vrai appel ``claude -p`` par usage LLM
du pipeline, sur une entree minuscule construite avec le vrai code de
l'etape (prompt/schema reels), pour attraper une erreur d'API (ex. le 400
``cache_control`` de TASK-746c) sans attendre une video d'une heure.

Saute par defaut (ADR-ad2e n'interdit pas de sauter un test, seulement un
repli silencieux en production) : ``CLIPPER_CLAUDE_INTEGRATION=1`` pour le
lancer, comme les autres tests d'integration reelle du depot.

    CLIPPER_CLAUDE_INTEGRATION=1 pytest tests/integration/test_smoke_real.py -v -s

``-s`` affiche la ligne ``llm_usage.jsonl`` (usage, modele, tokens, cout,
duree) de chaque appel reel.

``tests/test_smoke_coverage.py`` verifie mecaniquement (AST sur le code des
etapes, pas une recopie a la main) que ``USAGES`` ci-dessous couvre bien
tous les usages LLM presents dans le pipeline : le jour ou une etape gagne
un nouvel appel LLM sans smoke test associe, ce test unitaire (toujours
execute) le signale.

Le jury (ADR-ff87) note tous les candidats en un seul appel par juge : les 5
usages ``jury_<juge>`` partagent donc un seul ``jury.deliberate()`` reel,
cache (``functools.cache``) entre les 5 entrees pour ne payer qu'une fois.

Option mini-video (pipeline complet sur un extrait de 5 min, en config
auto) : voir ``test_smoke_mini_video_end_to_end`` plus bas, et
``docs/GUIDE.md`` (section Depannage) pour la commande.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import pytest

from clipper import captions, jury, llm, moments, parts, pipeline, qa, reframe, subtitles, transcribe, vision
from clipper.config import Config

pytestmark = pytest.mark.skipif(
    os.environ.get("CLIPPER_CLAUDE_INTEGRATION") != "1",
    reason="integration Claude : definir CLIPPER_CLAUDE_INTEGRATION=1 (consomme du quota)",
)


def _config(tmp_path: Path, sections: dict[str, dict[str, Any]] | None = None) -> Config:
    return Config(
        mode="auto",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections=sections or {},
    )


def _write_tiny_image(path: Path, label: str) -> None:
    image = np.full((120, 160, 3), 255, dtype=np.uint8)
    cv2.putText(image, label, (8, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f"ecriture image de test impossible : {path}")


# Grille minuscule (memes tables que rubric.toml, valeurs sans importance
# pour un test de fumee : seule la forme compte pour response_schema).
_SMOKE_RUBRIC = """
min_score = 60
max_moments_per_hour = 1000
always_keep_score = 1000
trend_keywords = ["record"]

[criteria.hook]
weight = 3
question = "La 1re phrase arrete-t-elle le scroll ?"
[criteria.standalone]
weight = 1
question = "Comprehensible seul ?"

[durations]
single_min = 20
single_max = 45
part_min = 60
part_max = 90
min_parts = 2
max_parts = 12
tolerance = 3

[bonus]
max_total = 6
replayed = 5
audio_peaks = 3
audio_peaks_full = 2
visual = 2

[exclusions]
sponsorblock_categories = ["sponsor", "intro", "outro", "selfpromo"]
"""


# --------------------------------------------------------------------------
# vocab (clipper.transcribe)
# --------------------------------------------------------------------------


def _smoke_vocab(tmp_path: Path) -> None:
    config = _config(tmp_path)
    meta = {
        "title": "Record impressionnant sur Rocket League",
        "description": "Zerator tente de battre le record de Kaydop en direct.",
    }
    words = transcribe._ask_vocab(meta, config)
    assert isinstance(words, list)


# --------------------------------------------------------------------------
# transcript_fix (clipper.transcribe)
# --------------------------------------------------------------------------


def _smoke_transcript_fix(tmp_path: Path) -> None:
    config = _config(tmp_path)
    chunk = [{
        "words": [
            {"word": " Bonjour"}, {"word": " a"}, {"word": " tous"},
            {"word": " et"}, {"word": " bienvenue"}, {"word": " ici."},
        ],
    }]
    stats = transcribe._FixStats()
    log_path = tmp_path / "transcript_fix_refusals.jsonl"
    transcribe._fix_chunk(chunk, ["Zerator"], config, log_path, stats)


# --------------------------------------------------------------------------
# moments (clipper.moments)
# --------------------------------------------------------------------------


_SMOKE_MOMENTS_TRANSCRIPT = {
    "segments": [
        {
            "start": 0.0, "end": 4.0,
            "words": [
                {"word": " Attendez", "start": 0.0, "end": 0.4},
                {"word": " je", "start": 0.4, "end": 0.6},
                {"word": " viens", "start": 0.6, "end": 0.9},
                {"word": " de", "start": 0.9, "end": 1.0},
                {"word": " voir", "start": 1.0, "end": 1.3},
                {"word": " un", "start": 1.3, "end": 1.4},
                {"word": " truc", "start": 1.4, "end": 1.7},
                {"word": " de", "start": 1.7, "end": 1.8},
                {"word": " fou.", "start": 1.8, "end": 2.2},
            ],
        },
        {
            "start": 4.0, "end": 8.0,
            "words": [
                {"word": " Le", "start": 4.0, "end": 4.1},
                {"word": " record", "start": 4.1, "end": 4.5},
                {"word": " du", "start": 4.5, "end": 4.6},
                {"word": " monde", "start": 4.6, "end": 5.0},
                {"word": " vient", "start": 5.0, "end": 5.3},
                {"word": " d'etre", "start": 5.3, "end": 5.6},
                {"word": " battu !", "start": 5.6, "end": 6.0},
            ],
        },
    ],
}


def _smoke_moments(tmp_path: Path) -> None:
    config = _config(tmp_path)
    rubric_path = tmp_path / "rubric.toml"
    rubric_path.write_text(_SMOKE_RUBRIC, encoding="utf-8")
    rubric = moments.load_rubric(rubric_path)
    sents = moments.split_sentences(_SMOKE_MOMENTS_TRANSCRIPT)
    lines = [moments._line(s) for s in sents]
    schema = moments.response_schema(rubric)
    prompt = moments._moments_prompt(
        "Extrait d'un live de jeu video (test de fumee).", rubric, lines, None
    )
    answer = llm.ask("moments", prompt, [], schema, config=config)
    assert isinstance(answer["moments"], list)


# --------------------------------------------------------------------------
# jury_avocat / jury_monteur / jury_retention / jury_conformite /
# jury_spectateur (clipper.jury) : un seul deliberate() reel, partage entre
# les 5 usages (chaque juge y fait deja son propre appel LLM, ADR-ff87).
# --------------------------------------------------------------------------


_SMOKE_JURY_RUBRIC = {
    "criteria": {
        "hook": {"weight": 3, "question": "La 1re phrase du clip arrete-t-elle le scroll ?"},
        "standalone": {"weight": 1, "question": "Le clip est-il comprehensible seul ?"},
    },
}

_SMOKE_JURY_CANDIDATES = [
    {"id": "fort", "text": "Rockstar vient de confirmer la date de sortie de GTA 6, et j'ai halluciné en le lisant."},
    {"id": "faible", "text": "Euh du coup comme je disais on va revenir la dessus plus tard, attendez je regarde le chat."},
]


@functools.cache
def _smoke_jury_result() -> dict[str, Any]:
    config = Config(mode="auto", workspace_dir=Path("workspace"), output_dir=Path("output"), _sections={})
    return jury.deliberate(
        _SMOKE_JURY_CANDIDATES, _SMOKE_JURY_RUBRIC,
        context="Extrait de test d'un live francais.", config=config,
    )


def _smoke_jury_judge(name: str) -> Callable[[Path], None]:
    def _run(tmp_path: Path) -> None:
        result = _smoke_jury_result()
        names = {j["name"] for j in result["judges"]}
        assert name in names

    return _run


# --------------------------------------------------------------------------
# vision (clipper.vision)
# --------------------------------------------------------------------------


def _smoke_vision(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_tiny_image(tmp_path / "frame_0.jpg", "BOOM")
    batch = [{"timecode": 1.0, "path": "frame_0.jpg"}]
    montage = vision._montage(batch, tmp_path, tmp_path, 96, 0)
    answer = llm.ask("vision", vision._prompt(batch), [montage], vision.response_schema(len(batch)), config=config)
    assert len(answer["frames"]) == 1


# --------------------------------------------------------------------------
# parts (clipper.parts)
# --------------------------------------------------------------------------


_SMOKE_PARTS_TRANSCRIPT = {
    "segments": [
        {"start": 0.0, "end": 3.0, "words": [
            {"word": " Alors", "start": 0.0, "end": 0.3},
            {"word": " voila", "start": 0.3, "end": 0.6},
            {"word": " ce", "start": 0.6, "end": 0.8},
            {"word": " qui", "start": 0.8, "end": 1.0},
            {"word": " s'est", "start": 1.0, "end": 1.3},
            {"word": " passe.", "start": 1.3, "end": 1.8},
        ]},
        {"start": 3.0, "end": 6.0, "words": [
            {"word": " Le", "start": 3.0, "end": 3.1},
            {"word": " record", "start": 3.1, "end": 3.5},
            {"word": " a", "start": 3.5, "end": 3.6},
            {"word": " ete", "start": 3.6, "end": 3.8},
            {"word": " pulverise.", "start": 3.8, "end": 4.5},
        ]},
        {"start": 6.0, "end": 9.0, "words": [
            {"word": " Personne", "start": 6.0, "end": 6.4},
            {"word": " ne", "start": 6.4, "end": 6.5},
            {"word": " s'y", "start": 6.5, "end": 6.7},
            {"word": " attendait.", "start": 6.7, "end": 7.3},
        ]},
        {"start": 9.0, "end": 12.0, "words": [
            {"word": " Et", "start": 9.0, "end": 9.1},
            {"word": " ce", "start": 9.1, "end": 9.3},
            {"word": " n'est", "start": 9.3, "end": 9.5},
            {"word": " que", "start": 9.5, "end": 9.7},
            {"word": " le", "start": 9.7, "end": 9.8},
            {"word": " debut.", "start": 9.8, "end": 10.3},
        ]},
    ],
}


def _smoke_parts(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sents = parts.split_sentences(_SMOKE_PARTS_TRANSCRIPT)
    d = {
        "single_min": 0.0, "single_max": 5.0, "part_min": 3.0, "part_max": 20.0,
        "min_parts": 2, "max_parts": 3, "tolerance": 1.0,
    }
    ov = parts.Overlap(seconds=1.0, min=0.5, max=2.0)
    moment = {
        "id": 0, "start": 0.0, "end": 12.0,
        "hook_text": "Accroche de test.", "justification": "Justification de test.", "parts": [],
    }
    # La reponse est deja validee au schema par llm.ask (SchemaError sinon) :
    # un rejet business ensuite (snap_cuts) n'est pas ce que ce test verifie.
    outcome, reason = parts._split(moment, sents, d, ov, config)
    assert outcome is not None or reason is not None


# --------------------------------------------------------------------------
# captions (clipper.captions)
# --------------------------------------------------------------------------


_SMOKE_CAPTIONS_TRANSCRIPT = {
    "segments": [{
        "start": 0.0, "end": 6.0,
        "words": [
            {"word": " Attendez,", "start": 0.0, "end": 0.4},
            {"word": " vous", "start": 0.4, "end": 0.6},
            {"word": " n'allez", "start": 0.6, "end": 0.9},
            {"word": " pas", "start": 0.9, "end": 1.1},
            {"word": " y", "start": 1.1, "end": 1.2},
            {"word": " croire.", "start": 1.2, "end": 1.7},
        ],
    }],
}


def _smoke_captions(tmp_path: Path) -> None:
    config = _config(tmp_path)
    settings = captions._settings(config)
    moment = {"id": 1, "parts_total": 1, "parts": [{"part": 1, "start": 0.0, "end": 6.0, "duration": 6.0}]}
    source = {"justification": "Un rebondissement inattendu.", "hook_text": "Attendez, vous n'allez pas y croire."}
    log_path = tmp_path / "captions_refusals.jsonl"
    clips = captions._process_moment(
        moment, source, _SMOKE_CAPTIONS_TRANSCRIPT, "fr", "Titre de la video de test",
        settings, int(settings["hook_words_max"]), int(settings["screen_title_words_max"]),
        config, log_path,
    )
    assert len(clips) == 1


# --------------------------------------------------------------------------
# layout (clipper.reframe, format crop -- option figee, SPEC-6127)
# --------------------------------------------------------------------------


def _smoke_layout(tmp_path: Path) -> None:
    config = _config(tmp_path)
    image_path = tmp_path / "plan_000.jpg"
    _write_tiny_image(image_path, "PLAN")
    plan = reframe._Plan(index=0, start=0.0, end=1.0, times=[0.5], tracks=[])
    answer = llm.ask(
        "layout", reframe._prompt(plan, 640, 360), [image_path], reframe.LAYOUT_SCHEMA, config=config,
    )
    reframe._check_answer(answer, plan)


# --------------------------------------------------------------------------
# emphasis (clipper.subtitles)
# --------------------------------------------------------------------------


def _smoke_emphasis(tmp_path: Path) -> None:
    config = _config(tmp_path)
    words = [{"word": " GTA"}, {"word": " six"}, {"word": " est"}, {"word": " enfin"}, {"word": " sorti"}]
    indices = subtitles._ask_emphasis(words, config)
    assert isinstance(indices, set)


# --------------------------------------------------------------------------
# qa (clipper.qa)
# --------------------------------------------------------------------------


def _smoke_qa(tmp_path: Path) -> None:
    config = _config(tmp_path)
    frame_path = tmp_path / "qa_frame.jpg"
    _write_tiny_image(frame_path, "QA")
    frames = [(frame_path, 1.0, ["frame"])]
    clip = {
        "duration": 8.0, "language": "fr", "layout": "letterbox",
        "screen_title": "Titre de test", "title": "Titre", "transcript": "Bonjour a tous.",
    }
    answer = llm.ask(
        "qa", qa._prompt(clip, frames, letterbox=True), [frame_path],
        qa.response_schema(letterbox=True, part=1), config=config,
    )
    assert isinstance(answer["issues"], list)


# --------------------------------------------------------------------------
# Registre : un usage LLM du pipeline -> comment lui faire un vrai appel
# minuscule. tests/test_smoke_coverage.py verifie qu'il n'en manque aucun.
# --------------------------------------------------------------------------

USAGES: dict[str, Callable[[Path], None]] = {
    "vocab": _smoke_vocab,
    "transcript_fix": _smoke_transcript_fix,
    "moments": _smoke_moments,
    "vision": _smoke_vision,
    "parts": _smoke_parts,
    "captions": _smoke_captions,
    "layout": _smoke_layout,
    "emphasis": _smoke_emphasis,
    "qa": _smoke_qa,
}
for _judge_name in ("retention", "spectateur", "monteur", "avocat", "conformite"):
    USAGES[f"jury_{_judge_name}"] = _smoke_jury_judge(_judge_name)
del _judge_name


@pytest.mark.parametrize("usage", sorted(USAGES))
def test_usage_makes_one_real_call(usage: str, tmp_path: Path) -> None:
    log_path = tmp_path / "llm_usage.jsonl"
    with llm.usage_log(log_path):
        USAGES[usage](tmp_path)
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            print(line)


# --------------------------------------------------------------------------
# Option mini-video : pipeline complet (auto) sur un extrait de 5 min d'une
# vidéo deja presente dans workspace/, chemin donne par CLIPPER_SMOKE_VIDEO.
# --------------------------------------------------------------------------

_SMOKE_VIDEO_ID = "smoketest01"  # 11 caracteres, comme un vrai id YouTube


@pytest.mark.skipif(
    not os.environ.get("CLIPPER_SMOKE_VIDEO"),
    reason="mini-video : definir CLIPPER_SMOKE_VIDEO=<chemin> vers une video existante de workspace/",
)
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent du PATH")
def test_smoke_mini_video_end_to_end(tmp_path: Path) -> None:
    source = Path(os.environ["CLIPPER_SMOKE_VIDEO"])
    if not source.is_file():
        pytest.fail(f"CLIPPER_SMOKE_VIDEO introuvable : {source}")

    workspace = tmp_path / "workspace"
    video_dir = workspace / _SMOKE_VIDEO_ID
    video_dir.mkdir(parents=True)
    clip_path = video_dir / f"{_SMOKE_VIDEO_ID}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(source), "-t", "300", "-c", "copy", str(clip_path)],
        check=True, capture_output=True,
    )
    meta = {
        "video_id": _SMOKE_VIDEO_ID,
        "title": "Extrait de test (smoke mini-video)",
        "description": "Extrait de 5 minutes utilise pour le test de fumee reel de bout en bout.",
        "duration": 300.0,
        "channel": "smoke",
        "language": "fr",
        "chapters": [],
        "heatmap": [],
        "sponsorblock_segments": [],
    }
    (video_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    rubric_path = tmp_path / "rubric.toml"
    rubric_path.write_text(_SMOKE_RUBRIC, encoding="utf-8")

    config = Config(
        mode="auto",
        workspace_dir=workspace,
        output_dir=tmp_path / "output",
        _sections={
            "moments": {"rubric_path": str(rubric_path)},
        },
    )
    url = f"https://www.youtube.com/watch?v={_SMOKE_VIDEO_ID}"
    state = pipeline.run(url, config=config)
    print(json.dumps(state, ensure_ascii=False))
    assert state["status"] in ("done", "queued"), state.get("reason")
