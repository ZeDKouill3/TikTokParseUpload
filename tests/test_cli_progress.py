"""Progression CLI pendant 'run'/'render' (TASK-5701).

Le pipeline reel n'est jamais sollicite : clipper.pipeline.run/render sont
remplaces par un faux qui rejoue les transitions d'etat exactement comme le
ferait le vrai pipeline (new_state/save_state), sans reseau, GPU, ni etape
reelle. Le CLI doit lire ces transitions depuis l'etat expose par
clipper.pipeline (workspace/<video_id>/pipeline.json) sans que pipeline.py ou
une etape n'aient ete modifies.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from clipper import pipeline
from clipper.config import Config

VIDEO_ID = "AAAAAAAAAAA"
URL = f"https://youtu.be/{VIDEO_ID}"
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _config(tmp_path) -> Config:
    return Config(mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")


def _patch_cli(monkeypatch, config, *, run=None, render=None):
    monkeypatch.setattr("clipper.__main__.load_config", lambda path="config.toml": config)
    if run is not None:
        monkeypatch.setattr(pipeline, "run", run)
    if render is not None:
        monkeypatch.setattr(pipeline, "render", render)


def _fake_run(config, *, fail_at=None, fail_reason="TransientLLMError: quota", gate=None):
    """gate = (nom_etape, reached_event, release_event) : bloque juste apres
    avoir enregistre l'etape comme 'running', le temps que le test observe
    l'affichage en direct, avant de la terminer."""

    def fake(url, *, config=config, force=False, **_ignored):
        state = pipeline.new_state(VIDEO_ID, url, config.mode)
        pipeline.save_state(state, config=config)
        now = _T0
        for name in pipeline.STEPS:
            step = state["steps"][name]
            step.update(status="running", started_at=_iso(now))
            pipeline.save_state(state, config=config)
            if gate is not None and name == gate[0]:
                gate[1].set()
                gate[2].wait(timeout=5)
            now += timedelta(seconds=2)
            if name == fail_at:
                step.update(status="failed", reason=fail_reason, finished_at=_iso(now))
                state.update(status="failed", reason=f"{name} : {fail_reason}")
                pipeline.save_state(state, config=config)
                return state
            step.update(status="done", finished_at=_iso(now))
            pipeline.save_state(state, config=config)
        state.update(status="done", clips=[])
        pipeline.save_state(state, config=config)
        return state

    return fake


def _fake_render(config):
    """Simule une reprise 'render' : download..parts deja faits avant l'appel
    (le test les ecrit sur disque en amont), captions..qa restent a faire."""

    def fake(video_id, *, config=config, force=False, **_ignored):
        state = pipeline.load_state(video_id, config=config)
        now = _T0
        for name in ("captions", "reframe", "subtitles", "render", "qa"):
            step = state["steps"][name]
            step.update(status="running", started_at=_iso(now))
            pipeline.save_state(state, config=config)
            now += timedelta(seconds=3)
            step.update(status="done", finished_at=_iso(now))
            pipeline.save_state(state, config=config)
        state.update(status="done", clips=[])
        pipeline.save_state(state, config=config)
        return state

    return fake


def test_run_affiche_demarree_puis_terminee_pour_chaque_etape(monkeypatch, isolated_cwd, capsys):
    config = _config(isolated_cwd)
    _patch_cli(monkeypatch, config, run=_fake_run(config))
    from clipper.__main__ import main

    exit_code = main(["run", URL])
    out = capsys.readouterr().out
    lines = out.splitlines()

    assert exit_code == 0
    for name in pipeline.STEPS:
        start_idx = lines.index(f"[{name}] démarrée")
        done_lines = [i for i, line in enumerate(lines) if line.startswith(f"[{name}] terminée en")]
        assert done_lines, f"aucune ligne de fin pour {name} : {lines}"
        assert done_lines[0] > start_idx
        assert lines[done_lines[0]].endswith(" s")


def test_run_respecte_lordre_des_etapes(monkeypatch, isolated_cwd, capsys):
    config = _config(isolated_cwd)
    _patch_cli(monkeypatch, config, run=_fake_run(config))
    from clipper.__main__ import main

    main(["run", URL])
    lines = capsys.readouterr().out.splitlines()
    start_positions = [lines.index(f"[{name}] démarrée") for name in pipeline.STEPS]
    assert start_positions == sorted(start_positions)


def test_run_affiche_lechec_avec_sa_raison(monkeypatch, isolated_cwd, capsys):
    config = _config(isolated_cwd)
    _patch_cli(monkeypatch, config, run=_fake_run(config, fail_at="scenes", fail_reason="TransientLLMError: quota depasse"))
    from clipper.__main__ import main

    main(["run", URL])
    out = capsys.readouterr().out
    assert "[scenes] démarrée" in out
    failure_lines = [line for line in out.splitlines() if line.startswith("[scenes]") and "échec" in line]
    assert failure_lines, out
    assert "quota depasse" in failure_lines[0]
    # les etapes qui suivent scenes dans STEPS n'ont jamais tourne.
    for name in pipeline.STEPS[pipeline.STEPS.index("scenes") + 1:]:
        assert f"[{name}] démarrée" not in out


def test_run_affiche_la_progression_pendant_quune_etape_tourne_encore(monkeypatch, isolated_cwd, capsys):
    """Reproduit le constat de la tache : sans cette fonctionnalite, le CLI
    reste muet pendant toute la duree d'une etape longue (le telechargement)."""
    config = _config(isolated_cwd)
    reached = threading.Event()
    release = threading.Event()
    _patch_cli(monkeypatch, config, run=_fake_run(config, gate=("download", reached, release)))
    from clipper.__main__ import main

    result: dict[str, int] = {}
    thread = threading.Thread(target=lambda: result.update(code=main(["run", URL])))
    thread.start()
    try:
        assert reached.wait(timeout=5), "l'etape 'download' n'a jamais ecrit son etat 'running'"

        deadline = time.monotonic() + 2.0
        seen_live = False
        while time.monotonic() < deadline:
            if "[download] démarrée" in capsys.readouterr().out:
                seen_live = True
                break
            time.sleep(0.02)
        assert seen_live, "le CLI n'affiche rien pendant qu'une etape tourne encore : elle reste muette comme avant"
    finally:
        release.set()
        thread.join(timeout=5)
    assert result["code"] == 0


def test_render_affiche_la_progression_sans_reannoncer_les_etapes_deja_faites(monkeypatch, isolated_cwd, capsys):
    config = _config(isolated_cwd)
    state = pipeline.new_state(VIDEO_ID, URL, config.mode)
    for name in ("download", "transcribe", "scenes", "audio", "moments", "vision", "parts"):
        state["steps"][name].update(status="done", started_at=_iso(_T0), finished_at=_iso(_T0 + timedelta(seconds=1)))
    state["status"] = "awaiting_review"
    pipeline.save_state(state, config=config)

    _patch_cli(monkeypatch, config, render=_fake_render(config))
    from clipper.__main__ import main

    exit_code = main(["render", VIDEO_ID])
    out = capsys.readouterr().out

    assert exit_code == 0
    for name in ("download", "transcribe", "scenes", "audio", "moments", "vision", "parts"):
        assert f"[{name}]" not in out, f"{name} n'a pas tourne pendant ce render : ne doit rien afficher"
    for name in ("captions", "reframe", "subtitles", "render", "qa"):
        assert f"[{name}] démarrée" in out
        assert any(line.startswith(f"[{name}] terminée en") for line in out.splitlines())
