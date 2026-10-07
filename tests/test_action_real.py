"""TASK-c8df7a5a7cf3 (SPEC-b0f3 R17, R18, ADR-4e57) : test reel optionnel des
candidats d'action sur un extrait court de VOD. Jamais lance par defaut ni en
CI (ADR-ad2e : saute explicitement, pas masque).

Saute sauf si ``CLIPPER_ACTION_REAL=1`` est positionne explicitement ;
``CLIPPER_ACTION_REAL_VIDEO`` donne le chemin d'un extrait de VOD de 10 min au
plus. Quand il tourne : copie l'extrait dans un workspace temporaire (l'original
n'est jamais touche), puis enchaine transcribe (vrai whisper, entree de scenes),
audio, scenes (peak_windows), action (vrai claude pour decrire les images) et
moments en « transcript+action » (vrai claude), avec la config reelle.
Plusieurs minutes, quota Claude consomme : ne jamais lancer en parallele d'un
autre travail lourd.

    $env:CLIPPER_ACTION_REAL = "1"
    $env:CLIPPER_ACTION_REAL_VIDEO = "C:\chemin\extrait.mp4"
    python -m pytest -q tests/test_action_real.py
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

VIDEO_ID = "actionreal1"
REAL_ENABLED = os.environ.get("CLIPPER_ACTION_REAL") == "1"

pytestmark = pytest.mark.skipif(
    not REAL_ENABLED,
    reason=(
        "test reel optionnel : positionne CLIPPER_ACTION_REAL=1 explicitement (et "
        "CLIPPER_ACTION_REAL_VIDEO=<extrait de VOD>) pour le lancer ; jamais lance par defaut ni en CI"
    ),
)


def _video_path() -> Path:
    raw = os.environ.get("CLIPPER_ACTION_REAL_VIDEO")
    if not raw:
        pytest.fail("CLIPPER_ACTION_REAL_VIDEO non positionnee : chemin d'un extrait de VOD (10 min au plus)")
    path = Path(raw)
    if not path.is_file():
        pytest.fail(f"CLIPPER_ACTION_REAL_VIDEO : fichier introuvable : {path}")
    return path


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(out.strip())


def test_action_candidates_on_a_real_excerpt(tmp_path):
    from clipper import action, audio, moments, scenes, transcribe
    from clipper.config import load_config

    source = _video_path()
    duration = _duration(source)
    assert duration <= 600, f"extrait trop long ({duration:.0f} s) : 10 min au plus"

    workspace = tmp_path / "workspace"
    video_dir = workspace / VIDEO_ID
    video_dir.mkdir(parents=True)
    video = video_dir / f"{VIDEO_ID}.mp4"
    shutil.copyfile(source, video)  # l'original n'est jamais touche
    (video_dir / "meta.json").write_text(
        json.dumps({"id": VIDEO_ID, "title": "Extrait de VOD", "channel": "test", "duration": duration}),
        encoding="utf-8",
    )

    config = load_config()
    config._sections.setdefault("moments", {}).update(
        {"rubric_path": "builtin:gaming-action", "candidates": "transcript+action"})
    config._sections.setdefault("action", {})["enabled"] = True
    config.workspace_dir = workspace
    config.output_dir = tmp_path / "output"
    config._sections.setdefault("feedback", {})["journal_path"] = str(tmp_path / "state" / "feedback.jsonl")

    transcribe.transcribe(VIDEO_ID, workspace, config=config)
    audio_settings = config.section("audio")
    audio.run(VIDEO_ID, workspace, sample_rate=audio_settings["sample_rate"],
              window_seconds=audio_settings["window_seconds"],
              median_window_seconds=audio_settings["median_window_seconds"],
              threshold_db=audio_settings["peak_threshold_db"])
    scenes.detect_scenes(video, workspace, VIDEO_ID, peak_windows=True, **config.section("scenes"))
    action.run(VIDEO_ID, workspace, config=config)
    moments.run(VIDEO_ID, workspace, config=config)

    result = json.loads((video_dir / "action.json").read_text(encoding="utf-8"))
    settings = result["settings"]
    passages = result["passages"]
    assert any(f.get("description") for p in passages for f in p["frames"]), \
        "aucun passage d'action avec des images decrites"
    image_cap = math.ceil(settings["max_images_per_hour"] * duration / 3600)
    assert result["images_sent"] <= image_cap
    assert result["llm_calls"] <= math.ceil(image_cap / settings["batch_size"])  # R18

    data = json.loads((video_dir / "moments.json").read_text(encoding="utf-8"))
    scored = [m for m in data["moments"] + data["rejected"] if m.get("source") == "action" and m.get("scores")]
    assert scored, "aucun candidat de source action note dans moments.json"
