"""Regression pour TASK-2562 : ecriture atomique de l'etat robuste face a un
PermissionError transitoire sur Path.replace (Windows, fichier lu par un
autre processus au meme instant : CLI de progression, interface web).

Ne depend pas de la plateforme : Path.replace est monkeypatche pour lever
PermissionError a volonte, sans avoir a reproduire un vrai verrou de fichier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipper import pipeline
from clipper.config import Config

VIDEO_ID = "abcdefghijk"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


def _config(tmp_path: Path) -> Config:
    return Config(mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")


def _flaky_replace(fail_times: int | None):
    """Remplace Path.replace : leve PermissionError `fail_times` fois (ou
    indefiniment si None) avant de retomber sur le vrai replace."""

    real_replace = Path.replace
    calls = {"n": 0}

    def fake_replace(self, target):
        calls["n"] += 1
        if fail_times is None or calls["n"] <= fail_times:
            raise PermissionError(13, "Acces refuse (simule)")
        return real_replace(self, target)

    return fake_replace, calls


def test_save_state_retries_on_transient_permission_error(tmp_path, monkeypatch):
    fake_replace, calls = _flaky_replace(fail_times=2)
    monkeypatch.setattr(Path, "replace", fake_replace)
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: sleeps.append(s))

    config = _config(tmp_path)
    state = pipeline.new_state(VIDEO_ID, URL, "auto")

    path = pipeline.save_state(state, config=config)

    assert calls["n"] == 3
    assert sleeps == [pipeline._REPLACE_DELAY_S, pipeline._REPLACE_DELAY_S]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["video_id"] == VIDEO_ID


def test_save_state_raises_after_persistent_permission_error(tmp_path, monkeypatch):
    fake_replace, calls = _flaky_replace(fail_times=None)
    monkeypatch.setattr(Path, "replace", fake_replace)
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)

    config = _config(tmp_path)
    state = pipeline.new_state(VIDEO_ID, URL, "auto")

    with pytest.raises(PermissionError):
        pipeline.save_state(state, config=config)

    assert calls["n"] == pipeline._REPLACE_ATTEMPTS
    # Pas de perte silencieuse : le fichier final n'existe pas, seul le
    # fichier temporaire (donnee non publiee) est present.
    final = tmp_path / "workspace" / VIDEO_ID / pipeline.STATE_FILE
    assert not final.exists()
