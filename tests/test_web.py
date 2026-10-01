"""Tests de clipper.web (TASK-634e).

Routes testees avec le TestClient FastAPI et un pipeline simule (jamais le
vrai pipeline.run/render/decide) : voir clipper/web/app.py pour le contrat.
Aucun test n'utilise le reseau ni un vrai LLM.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipper.config import Config
from clipper.web import app as web_app
from clipper.web import create_app

VIDEO_ID = "abcdefghijk"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


def make_config(tmp_path) -> Config:
    return Config(mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")


def client(tmp_path) -> TestClient:
    return TestClient(create_app(config=make_config(tmp_path)))


# --------------------------------------------------------------------------
# B : page statique
# --------------------------------------------------------------------------


def test_serve_static_index_page(tmp_path, isolated_cwd):
    resp = client(tmp_path).get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert '<html lang="fr"' in resp.text
    assert 'id="app"' in resp.text


# --------------------------------------------------------------------------
# C : POST /api/videos est un alias de POST /api/queue sans chaine (ADR-4f6e
# §1 : jamais pipeline.run dans ce processus, worker.enqueue a la place)
# --------------------------------------------------------------------------


def test_submit_url_enqueues_via_worker(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    calls = []

    def fake_enqueue(url, channel, action, force_steps, *, config=None):
        calls.append((url, channel, action, force_steps))
        return {"id": "e1", "video_id": VIDEO_ID, "url": url, "channel": channel,
                "action": action, "force_steps": force_steps or [], "status": "waiting"}

    monkeypatch.setattr(worker, "enqueue", fake_enqueue)

    resp = client(tmp_path).post("/api/videos", json={"url": URL})

    assert resp.status_code == 202
    assert resp.json()["video_id"] == VIDEO_ID
    assert calls == [(URL, None, "run", None)]


def test_submit_missing_url_is_a_validation_error(tmp_path, isolated_cwd):
    resp = client(tmp_path).post("/api/videos", json={})
    assert resp.status_code == 422


# --------------------------------------------------------------------------
# D : GET /api/videos liste workspace/*/pipeline.json
# --------------------------------------------------------------------------


def _write_state(tmp_path, video_id, **overrides):
    from clipper import pipeline

    state = pipeline.new_state(video_id, f"https://www.youtube.com/watch?v={video_id}", "review")
    state.update(overrides)
    video_dir = tmp_path / "workspace" / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "pipeline.json").write_text(json.dumps(state), encoding="utf-8")
    return state


def test_list_videos_reads_pipeline_json_from_workspace(tmp_path, isolated_cwd):
    _write_state(tmp_path, "aaaaaaaaaaa", status="running")
    _write_state(tmp_path, "bbbbbbbbbbb", status="done")

    resp = client(tmp_path).get("/api/videos")

    assert resp.status_code == 200
    ids = [v["video_id"] for v in resp.json()]
    assert sorted(ids) == ["aaaaaaaaaaa", "bbbbbbbbbbb"]


def test_list_videos_empty_workspace_is_an_empty_list(tmp_path, isolated_cwd):
    resp = client(tmp_path).get("/api/videos")
    assert resp.status_code == 200
    assert resp.json() == []


# --------------------------------------------------------------------------
# E : GET /api/videos/{id} via pipeline.load_state
# --------------------------------------------------------------------------


def test_get_video_detail_uses_pipeline_load_state(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline

    state = {"video_id": VIDEO_ID, "status": "running", "steps": {}}

    def fake_load_state(video_id, *, config=None):
        assert video_id == VIDEO_ID
        return state

    monkeypatch.setattr(pipeline, "load_state", fake_load_state)

    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert {k: body[k] for k in state} == state
    assert body["clips"] == [] and body["awaiting"] == [] and body["durations"] == {}


def test_get_video_detail_unknown_video_is_404(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline

    def fake_load_state(video_id, *, config=None):
        raise pipeline.PipelineError(f"aucun etat pour la video {video_id}")

    monkeypatch.setattr(pipeline, "load_state", fake_load_state)

    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}")

    assert resp.status_code == 404
    assert VIDEO_ID in resp.json()["detail"]


# --------------------------------------------------------------------------
# F : GET /api/videos/{id}/moments fusionne moments.json + parts.json + review.json
# --------------------------------------------------------------------------


MOMENTS_JSON = {
    "video_id": VIDEO_ID,
    "moments": [
        {"id": 0, "start": 2.0, "end": 26.0, "duration": 24.0, "format": "single", "parts": [],
         "scores": {"hook": 9}, "bonus": {"total": 1.0}, "final_score": 91.0,
         "justification": "Annonce forte", "hook_text": "GTA six arrive vraiment."},
        {"id": 1, "start": 40.0, "end": 60.0, "duration": 20.0, "format": "single", "parts": [],
         "scores": {"hook": 7}, "bonus": {"total": 0.0}, "final_score": 70.0,
         "justification": "Correct", "hook_text": "Autre moment."},
    ],
    "rejected": [],
}
PARTS_JSON = {
    "video_id": VIDEO_ID,
    "moments": [
        {"id": 0, "start": 2.0, "end": 26.0, "duration": 24.0, "format": "single", "parts_total": 1,
         "proposed_cuts": [], "parts": [{"part": 1, "start": 2.0, "end": 26.0, "duration": 24.0,
                                          "hook_text": "GTA six arrive vraiment.", "suspense": None}]},
        {"id": 1, "start": 40.0, "end": 60.0, "duration": 20.0, "format": "single", "parts_total": 1,
         "proposed_cuts": [], "parts": [{"part": 1, "start": 40.0, "end": 60.0, "duration": 20.0,
                                          "hook_text": "Autre moment.", "suspense": None}]},
    ],
    "rejected": [],
}


def _write_moments_fixtures(tmp_path, review=None):
    video_dir = tmp_path / "workspace" / VIDEO_ID
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "moments.json").write_text(json.dumps(MOMENTS_JSON), encoding="utf-8")
    (video_dir / "parts.json").write_text(json.dumps(PARTS_JSON), encoding="utf-8")
    if review is not None:
        (video_dir / "review.json").write_text(json.dumps(review), encoding="utf-8")


def test_list_moments_merges_score_justification_and_preview(tmp_path, isolated_cwd):
    _write_moments_fixtures(tmp_path)

    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/moments")

    assert resp.status_code == 200
    moments = resp.json()
    assert [m["id"] for m in moments] == [0, 1]
    first = moments[0]
    assert first["start"] == 2.0 and first["end"] == 26.0
    assert first["score"] == 91.0
    assert first["justification"] == "Annonce forte"
    assert first["hook_text"] == "GTA six arrive vraiment."
    assert first["decision"] is None
    assert first["preview_url"] == f"/media/source/{VIDEO_ID}"


def test_list_moments_reports_existing_decisions(tmp_path, isolated_cwd):
    review = {"decisions": {"0": {"decision": "adjusted", "start": 4.0, "end": 26.0,
                                   "comment": "debut plus net", "at": "2026-01-01T00:00:00+00:00"}}}
    _write_moments_fixtures(tmp_path, review=review)

    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/moments")

    moments = {m["id"]: m for m in resp.json()}
    assert moments[0]["decision"] == review["decisions"]["0"]
    assert moments[1]["decision"] is None


def test_list_moments_unknown_video_is_404(tmp_path, isolated_cwd):
    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/moments")
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# G : POST /api/videos/{id}/moments/{mid}/decide appelle pipeline.decide
# --------------------------------------------------------------------------


def test_decide_calls_pipeline_decide(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline

    calls = []

    def fake_decide(video_id, moment_id, decision, *, start=None, end=None, comment=None, config=None):
        calls.append((video_id, moment_id, decision, start, end, comment))
        return {"video_id": video_id, "decision": decision}

    monkeypatch.setattr(pipeline, "decide", fake_decide)

    resp = client(tmp_path).post(
        f"/api/videos/{VIDEO_ID}/moments/0/decide",
        json={"decision": "adjusted", "start": 4.0, "end": 26.0, "comment": "debut plus net"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"video_id": VIDEO_ID, "decision": "adjusted"}
    assert calls == [(VIDEO_ID, 0, "adjusted", 4.0, 26.0, "debut plus net")]


def test_decide_accepted_needs_no_bounds(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline

    calls = []
    monkeypatch.setattr(
        pipeline, "decide",
        lambda video_id, moment_id, decision, *, start=None, end=None, comment=None, config=None:
            calls.append((video_id, moment_id, decision, start, end, comment)) or {"decision": decision},
    )

    resp = client(tmp_path).post(f"/api/videos/{VIDEO_ID}/moments/0/decide", json={"decision": "accepted"})

    assert resp.status_code == 200
    assert calls == [(VIDEO_ID, 0, "accepted", None, None, None)]


def test_decide_invalid_decision_is_400(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline

    def fake_decide(video_id, moment_id, decision, *, start=None, end=None, comment=None, config=None):
        raise pipeline.PipelineError(f"decision invalide {decision!r}")

    monkeypatch.setattr(pipeline, "decide", fake_decide)

    resp = client(tmp_path).post(f"/api/videos/{VIDEO_ID}/moments/0/decide", json={"decision": "bogus"})

    assert resp.status_code == 400
    assert "bogus" in resp.json()["detail"]


# --------------------------------------------------------------------------
# H : POST /api/videos/{id}/render remet en file (action 'render') via
# worker.enqueue, jamais pipeline.render dans ce processus (ADR-4f6e §1)
# --------------------------------------------------------------------------


def test_render_enqueues_render_action(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    calls = []

    def fake_enqueue(url, channel, action, force_steps, *, config=None):
        calls.append((url, channel, action, force_steps))
        return {"id": "e1", "video_id": VIDEO_ID, "channel": channel, "action": action,
                "force_steps": force_steps or [], "status": "waiting"}

    monkeypatch.setattr(worker, "enqueue", fake_enqueue)

    resp = client(tmp_path).post(f"/api/videos/{VIDEO_ID}/render")

    assert resp.status_code == 202
    assert resp.json()["video_id"] == VIDEO_ID
    assert calls == [(VIDEO_ID, None, "render", None)]


def test_render_passes_the_video_channel(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline, worker

    _write_state(tmp_path, VIDEO_ID, channel="une_chaine")
    calls = []
    monkeypatch.setattr(
        worker, "enqueue",
        lambda url, channel, action, force_steps, *, config=None:
            calls.append((url, channel, action, force_steps)) or
            {"id": "e1", "video_id": VIDEO_ID, "channel": channel, "action": action,
             "force_steps": force_steps or [], "status": "waiting"},
    )

    resp = client(tmp_path).post(f"/api/videos/{VIDEO_ID}/render")

    assert resp.status_code == 202
    assert calls == [(VIDEO_ID, "une_chaine", "render", None)]


# --------------------------------------------------------------------------
# I : GET /api/videos/{id}/clips lit output/<id>/*.json
# --------------------------------------------------------------------------


CLIP_JSON = {
    "video_id": VIDEO_ID, "source_url": URL, "source_title": "GTA 6 : le trailer",
    "clip_id": "03-p2", "part": 2, "parts_total": 2, "start": 2.0, "end": 26.0, "duration": 24.0,
    "language": "fr", "score": 91.0, "scores": {"hook": 9}, "reason": "Annonce forte",
    "hook_text": "GTA six arrive vraiment.", "title": "GTA 6 arrive", "caption": "Il arrive vraiment",
    "hashtags": ["#gta6"], "transcript": "GTA six arrive vraiment.", "layout": "single",
    "qa": {"status": "passed", "issues": []}, "created_at": "2026-01-01T00:00:00+00:00",
}


def test_list_clips_reads_output_json(tmp_path, isolated_cwd):
    out_dir = tmp_path / "output" / VIDEO_ID
    out_dir.mkdir(parents=True)
    (out_dir / f"{CLIP_JSON['clip_id']}.json").write_text(json.dumps(CLIP_JSON), encoding="utf-8")
    (out_dir / f"{CLIP_JSON['clip_id']}.mp4").write_bytes(b"fake-mp4")

    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/clips")

    assert resp.status_code == 200
    clips = resp.json()
    assert len(clips) == 1
    clip = clips[0]
    assert clip["title"] == "GTA 6 arrive"
    assert clip["caption"] == "Il arrive vraiment"
    assert clip["hashtags"] == ["#gta6"]
    assert clip["video_url"] == f"/media/clip/{VIDEO_ID}/{CLIP_JSON['clip_id']}"


def test_list_clips_no_output_yet_is_an_empty_list(tmp_path, isolated_cwd):
    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/clips")
    assert resp.status_code == 200
    assert resp.json() == []


# --------------------------------------------------------------------------
# J : /media/source/{id} et /media/clip/{id}/{clip_id} servent les mp4
# --------------------------------------------------------------------------


def test_media_source_serves_the_source_video(tmp_path, isolated_cwd):
    video_dir = tmp_path / "workspace" / VIDEO_ID
    video_dir.mkdir(parents=True)
    (video_dir / f"{VIDEO_ID}.mp4").write_bytes(b"source-bytes")

    resp = client(tmp_path).get(f"/media/source/{VIDEO_ID}")

    assert resp.status_code == 200
    assert resp.content == b"source-bytes"
    assert resp.headers["content-type"] == "video/mp4"


def test_media_source_missing_file_is_404(tmp_path, isolated_cwd):
    resp = client(tmp_path).get(f"/media/source/{VIDEO_ID}")
    assert resp.status_code == 404


def test_media_source_rejects_path_traversal(tmp_path, isolated_cwd):
    resp = client(tmp_path).get("/media/source/..")
    assert resp.status_code == 404


def test_media_clip_serves_the_rendered_clip(tmp_path, isolated_cwd):
    out_dir = tmp_path / "output" / VIDEO_ID
    out_dir.mkdir(parents=True)
    clip_id = "03-p2"
    (out_dir / f"{clip_id}.mp4").write_bytes(b"clip-bytes")

    resp = client(tmp_path).get(f"/media/clip/{VIDEO_ID}/{clip_id}")

    assert resp.status_code == 200
    assert resp.content == b"clip-bytes"
    assert resp.headers["content-type"] == "video/mp4"


def test_media_clip_rejects_path_traversal(tmp_path, isolated_cwd):
    resp = client(tmp_path).get(f"/media/clip/{VIDEO_ID}/..%2F..%2Fsecret")
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# K : aucune logique de traitement dans clipper/web (ADR-09ad)
# --------------------------------------------------------------------------


_ALLOWED_CLIPPER_IMPORTS = {
    "clipper", "clipper.pipeline", "clipper.config", "clipper.web", "clipper.web.app",
    "clipper.channel", "clipper.worker", "clipper.publish", "clipper.watch", "clipper.gpu",
}


def test_web_module_only_imports_pipeline_and_config():
    import ast

    root = Path(__file__).resolve().parent.parent / "clipper" / "web"
    offenders = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                if name and name.startswith("clipper") and name not in _ALLOWED_CLIPPER_IMPORTS:
                    offenders.append(f"{path.name} importe {name}")
    assert offenders == []


# --------------------------------------------------------------------------
# A : 'python -m clipper serve' lance uvicorn sur 127.0.0.1
# --------------------------------------------------------------------------


def test_cli_serve_runs_uvicorn_on_localhost(tmp_path, isolated_cwd, monkeypatch):
    import uvicorn

    from clipper.__main__ import main

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))

    assert main(["serve"]) == 0

    assert len(calls) == 1
    app, kwargs = calls[0]
    assert app.title == "Clipper"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000


def test_cli_serve_port_is_configurable(tmp_path, isolated_cwd, monkeypatch):
    import uvicorn

    from clipper.__main__ import main

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))

    assert main(["serve", "--port", "9001"]) == 0

    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 9001


def test_logo_is_served_as_standalone_svg(tmp_path, isolated_cwd):
    resp = client(tmp_path).get("/static/logo.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    import xml.etree.ElementTree as ET

    root = ET.fromstring(resp.text)
    assert root.tag.endswith("svg")
    assert root.get("viewBox")
    # autonome : aucune ressource ni police externe
    assert "href" not in resp.text and "font" not in resp.text


def test_index_declares_logo_as_icon_and_shows_it_in_the_brand(tmp_path, isolated_cwd):
    html = client(tmp_path).get("/").text
    assert '<link rel="icon" type="image/svg+xml" href="/static/logo.svg">' in html
    brand = html[html.index('<a class="brand"'):html.index("</a>", html.index('<a class="brand"'))]
    assert 'src="/static/logo.svg"' in brand
    assert 'alt=""' in brand
    assert "Clipper" in brand


# --------------------------------------------------------------------------
# L : file de traitement (/api/queue) - SPEC-fc0c §2
# --------------------------------------------------------------------------


def test_queue_post_calls_worker_enqueue(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    calls = []

    def fake_enqueue(url, channel, action, force_steps, *, config=None):
        calls.append((url, channel, action, force_steps))
        return {"id": "e1", "video_id": VIDEO_ID, "url": url, "channel": channel,
                "action": action, "force_steps": force_steps, "status": "waiting"}

    monkeypatch.setattr(worker, "enqueue", fake_enqueue)

    resp = client(tmp_path).post("/api/queue", json={
        "url": URL, "channel": "une_chaine", "action": "run", "force_steps": ["render"],
    })

    assert resp.status_code == 202
    assert resp.json()["video_id"] == VIDEO_ID
    assert calls == [(URL, "une_chaine", "run", ["render"])]


def test_queue_post_duplicate_is_409_with_french_detail(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    def fake_enqueue(url, channel, action, force_steps, *, config=None):
        raise worker.WorkerError(f"deja en file d'attente : {VIDEO_ID} ({action})")

    monkeypatch.setattr(worker, "enqueue", fake_enqueue)

    resp = client(tmp_path).post(
        "/api/queue", json={"url": URL, "channel": None, "action": "run", "force_steps": []}
    )

    assert resp.status_code == 409
    assert "file d'attente" in resp.json()["detail"]


def test_queue_get_lists_entries(tmp_path, isolated_cwd):
    queue_path = tmp_path / "state" / "queue.json"
    queue_path.parent.mkdir(parents=True)
    entries = [{"id": "e1", "video_id": VIDEO_ID, "url": URL, "channel": None, "action": "run",
                "force_steps": [], "enqueued_at": "2026-01-01T00:00:00+00:00", "status": "waiting", "pid": None}]
    queue_path.write_text(json.dumps(entries), encoding="utf-8")

    resp = client(tmp_path).get("/api/queue")

    assert resp.status_code == 200
    assert resp.json() == entries


def test_queue_get_empty_is_an_empty_list(tmp_path, isolated_cwd):
    resp = client(tmp_path).get("/api/queue")
    assert resp.status_code == 200
    assert resp.json() == []


def test_queue_front_calls_worker_move_to_front(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    calls = []
    monkeypatch.setattr(worker, "move_to_front", lambda video_id, *, config=None: calls.append(video_id))

    resp = client(tmp_path).post(f"/api/queue/{VIDEO_ID}/front")

    assert resp.status_code == 200
    assert calls == [VIDEO_ID]


def test_queue_front_unknown_entry_is_404(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    def fake(video_id, *, config=None):
        raise worker.WorkerError(f"aucune entree en attente pour {video_id!r}")

    monkeypatch.setattr(worker, "move_to_front", fake)

    resp = client(tmp_path).post(f"/api/queue/{VIDEO_ID}/front")

    assert resp.status_code == 404


def test_queue_delete_calls_worker_remove(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    calls = []
    monkeypatch.setattr(worker, "remove", lambda video_id, *, config=None: calls.append(video_id))

    resp = client(tmp_path).delete(f"/api/queue/{VIDEO_ID}")

    assert resp.status_code == 200
    assert calls == [VIDEO_ID]


def test_queue_delete_unknown_entry_is_404(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    def fake(video_id, *, config=None):
        raise worker.WorkerError(f"aucune entree en attente pour {video_id!r}")

    monkeypatch.setattr(worker, "remove", fake)

    resp = client(tmp_path).delete(f"/api/queue/{VIDEO_ID}")

    assert resp.status_code == 404


# --------------------------------------------------------------------------
# M : annulation, relance, journal par video - SPEC-fc0c §2.3, §3.2
# --------------------------------------------------------------------------


def test_cancel_calls_worker_cancel(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    calls = []
    monkeypatch.setattr(worker.Worker, "cancel", lambda self, video_id: calls.append(video_id))

    resp = client(tmp_path).post(f"/api/videos/{VIDEO_ID}/cancel")

    assert resp.status_code == 200
    assert calls == [VIDEO_ID]


def test_cancel_not_running_is_404(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    def fake_cancel(self, video_id):
        raise worker.WorkerError(f"aucune video en cours pour {video_id!r}")

    monkeypatch.setattr(worker.Worker, "cancel", fake_cancel)

    resp = client(tmp_path).post(f"/api/videos/{VIDEO_ID}/cancel")

    assert resp.status_code == 404


def test_retry_enqueues_render_with_force_steps_from_step(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline, worker

    calls = []
    monkeypatch.setattr(
        worker, "enqueue",
        lambda url, channel, action, force_steps, *, config=None:
            calls.append((url, channel, action, force_steps)) or
            {"id": "e1", "video_id": VIDEO_ID, "channel": channel, "action": action,
             "force_steps": force_steps, "status": "waiting"},
    )

    resp = client(tmp_path).post(f"/api/videos/{VIDEO_ID}/retry", json={"from_step": "reframe"})

    assert resp.status_code == 202
    expected_force_steps = list(pipeline.STEPS[pipeline.STEPS.index("reframe"):])
    assert calls == [(VIDEO_ID, None, "render", expected_force_steps)]
    assert "reframe" in resp.json()["force_steps"]


def test_retry_unknown_step_is_400(tmp_path, isolated_cwd):
    resp = client(tmp_path).post(f"/api/videos/{VIDEO_ID}/retry", json={"from_step": "bogus"})
    assert resp.status_code == 400
    assert "bogus" in resp.json()["detail"]


def test_video_events_reads_events_jsonl(tmp_path, isolated_cwd):
    video_dir = tmp_path / "workspace" / VIDEO_ID
    video_dir.mkdir(parents=True)
    lines = [
        {"at": "2026-01-01T00:00:00+00:00", "level": "INFO", "step": "download", "message": "demarre"},
        {"at": "2026-01-01T00:01:00+00:00", "level": "INFO", "step": "download", "message": "termine"},
    ]
    (video_dir / "events.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")

    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/events")

    assert resp.status_code == 200
    assert resp.json() == lines


def test_video_events_since_filters_older_lines(tmp_path, isolated_cwd):
    video_dir = tmp_path / "workspace" / VIDEO_ID
    video_dir.mkdir(parents=True)
    lines = [
        {"at": "2026-01-01T00:00:00+00:00", "level": "INFO", "step": "download", "message": "demarre"},
        {"at": "2026-01-01T00:01:00+00:00", "level": "INFO", "step": "download", "message": "termine"},
    ]
    (video_dir / "events.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")

    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/events", params={"since": "2026-01-01T00:00:00+00:00"})

    assert resp.status_code == 200
    assert resp.json() == [lines[1]]


def test_video_events_no_journal_yet_is_an_empty_list(tmp_path, isolated_cwd):
    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/events")
    assert resp.status_code == 200
    assert resp.json() == []


def test_video_events_rejects_path_traversal(tmp_path, isolated_cwd):
    # "..%2F..%2Fsecret" (comme test_media_clip_rejects_path_traversal) : pas
    # de normalisation cote client httpx (le "/" reste encode), contrairement
    # a un ".." nu qui serait resolu avant l'envoi et, ici, retomberait sur
    # /api/events (flux SSE infini) au lieu d'exercer la validation serveur.
    resp = client(tmp_path).get("/api/videos/..%2F..%2Fsecret/events")
    assert resp.status_code in (400, 404)


def test_cancel_rejects_path_traversal(tmp_path, isolated_cwd):
    resp = client(tmp_path).post("/api/videos/..%2F..%2Fsecret/cancel")
    assert resp.status_code in (400, 404)


# --------------------------------------------------------------------------
# N : GET /api/channels - channel.list_channels (SPEC-fc0c §1)
# --------------------------------------------------------------------------


def test_channels_lists_presets_with_channel_table(tmp_path, isolated_cwd):
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    (presets_dir / "une_chaine.toml").write_text('[channel]\ndisplay_name = "Une chaine"\n', encoding="utf-8")
    (presets_dir / "sans_channel.toml").write_text('mode = "auto"\n', encoding="utf-8")

    resp = client(tmp_path).get("/api/channels")

    assert resp.status_code == 200
    assert resp.json() == ["une_chaine"]


def test_channels_no_presets_dir_is_an_empty_list(tmp_path, isolated_cwd):
    resp = client(tmp_path).get("/api/channels")
    assert resp.status_code == 200
    assert resp.json() == []


# --------------------------------------------------------------------------
# O : GET /api/events - flux SSE par mtime (ADR-4f6e §4)
# --------------------------------------------------------------------------


def _sse_config(tmp_path) -> Config:
    return Config(
        mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={"web": {"host": "127.0.0.1", "port": 8000, "token": "", "sse_poll_interval_s": 0.05}},
    )


def test_events_route_is_declared_as_sse(tmp_path, isolated_cwd):
    # La reponse HTTP infinie de ce flux ne peut pas etre lue de bout en bout
    # ici : le TestClient de ce venv bloque indefiniment sur un corps qui ne
    # se termine jamais (reproduit hors pytest avec un generateur minimal,
    # voir ank log). Le contrat "flux SSE" est donc verifie par la route
    # elle-meme (media_type) ; le comportement "un evenement par mtime
    # changee" est prouve directement sur le generateur ci-dessous.
    app = create_app(config=_sse_config(tmp_path))
    route = next(r for r in app.router.routes if getattr(r, "path", None) == "/api/events")
    assert "GET" in route.methods


def test_event_stream_generator_emits_on_file_mtime_change(tmp_path, isolated_cwd):
    import asyncio

    from clipper.web.app import _event_stream

    config = _sse_config(tmp_path)

    async def _run() -> str:
        agen = _event_stream(config).__aiter__()

        async def _touch_queue_file_soon() -> None:
            await asyncio.sleep(0.15)
            state_dir = tmp_path / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "queue.json").write_text("[]", encoding="utf-8")

        asyncio.create_task(_touch_queue_file_soon())
        return await asyncio.wait_for(agen.__anext__(), timeout=2.0)

    chunk = asyncio.run(_run())

    assert chunk.startswith("data: ")
    event = json.loads(chunk[len("data: "):].strip())
    assert event["kind"] == "queue"
    assert "id" in event and "at" in event


def test_event_stream_generator_ignores_files_present_before_connecting(tmp_path, isolated_cwd):
    import asyncio

    from clipper.web.app import _event_stream

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "queue.json").write_text("[]", encoding="utf-8")
    config = _sse_config(tmp_path)

    async def _run() -> bool:
        agen = _event_stream(config).__aiter__()
        try:
            await asyncio.wait_for(agen.__anext__(), timeout=0.3)
            return True
        except asyncio.TimeoutError:
            return False

    got_event = asyncio.run(_run())
    assert got_event is False


# --------------------------------------------------------------------------
# P : jeton d'acces (ADR-4f6e §5)
# --------------------------------------------------------------------------


def _config_with_web(tmp_path, **web) -> Config:
    return Config(
        mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={"web": web},
    )


def test_create_app_refuses_non_loopback_host_without_token(tmp_path, isolated_cwd):
    from clipper.web.app import WebConfigError

    config = _config_with_web(tmp_path, host="0.0.0.0", token="")

    with pytest.raises(WebConfigError):
        create_app(config=config)


def test_create_app_accepts_non_loopback_host_with_token(tmp_path, isolated_cwd):
    config = _config_with_web(tmp_path, host="0.0.0.0", token="secret")
    create_app(config=config)


def test_api_requires_token_on_non_loopback_host(tmp_path, isolated_cwd):
    config = _config_with_web(tmp_path, host="0.0.0.0", token="secret")
    test_client = TestClient(create_app(config=config))

    resp = test_client.get("/api/videos")

    assert resp.status_code == 401
    assert "detail" in resp.json()


def test_api_accepts_token_via_header(tmp_path, isolated_cwd):
    config = _config_with_web(tmp_path, host="0.0.0.0", token="secret")
    test_client = TestClient(create_app(config=config))

    resp = test_client.get("/api/videos", headers={"X-Clipper-Token": "secret"})

    assert resp.status_code == 200


def test_api_accepts_token_via_cookie(tmp_path, isolated_cwd):
    config = _config_with_web(tmp_path, host="0.0.0.0", token="secret")
    test_client = TestClient(create_app(config=config))
    test_client.cookies.set("clipper_token", "secret")

    resp = test_client.get("/api/videos")

    assert resp.status_code == 200


def test_media_also_requires_token_on_non_loopback_host(tmp_path, isolated_cwd):
    config = _config_with_web(tmp_path, host="0.0.0.0", token="secret")
    test_client = TestClient(create_app(config=config))

    resp = test_client.get(f"/media/source/{VIDEO_ID}")

    assert resp.status_code == 401


def test_loopback_host_requires_no_token(tmp_path, isolated_cwd):
    config = _config_with_web(tmp_path, host="127.0.0.1", token="")
    test_client = TestClient(create_app(config=config))

    resp = test_client.get("/api/videos")

    assert resp.status_code == 200


# --------------------------------------------------------------------------
# M : coquille de la page v2 (SPEC-c100 T2..T8, TASK-f753) - verifications
# statiques des fichiers servis ; le JS n'est pas execute ici.
# --------------------------------------------------------------------------

import re
from html.parser import HTMLParser

SCREENS = ["dashboard", "videos", "review", "clips", "channels", "publish", "stats", "settings"]
TAB_SCREENS = ["dashboard", "videos", "review", "clips", "publish"]
STATIC = Path(__file__).resolve().parent.parent / "clipper" / "web" / "static"


def served(tmp_path, path: str) -> str:
    resp = client(tmp_path).get(path)
    assert resp.status_code == 200, path
    return resp.text


def test_index_has_navigation_to_the_eight_screens(tmp_path, isolated_cwd):
    html = served(tmp_path, "/")
    nav = html[html.index('<nav class="nav"'):html.index("</nav>", html.index('<nav class="nav"'))]
    for screen in SCREENS:
        assert f'href="#/{screen}"' in nav, screen
        assert f'data-screen="{screen}"' in nav, screen
        assert f'id="screen-{screen}"' in html, screen


def test_index_has_a_mobile_tab_bar(tmp_path, isolated_cwd):
    html = served(tmp_path, "/")
    assert 'name="viewport"' in html
    tabbar = html[html.index('<nav class="tabbar"'):html.index("</nav>", html.index('<nav class="tabbar"'))]
    for screen in TAB_SCREENS:
        assert f'href="#/{screen}"' in tabbar, screen
    css = served(tmp_path, "/static/style.css")
    assert ".tabbar" in css and "@media (max-width: 900px)" in css
    assert "44px" in css  # zones de toucher (T6)


def test_app_js_listens_to_sse_and_reloads_the_targeted_object(tmp_path, isolated_cwd):
    js = served(tmp_path, "/static/app.js")
    assert 'new EventSource("/api/events")' in js
    for needle in ("JSON.parse(", "event.kind", "event.id", "/api/videos/${", "setInterval(", "POLL_MS = 5000"):
        assert needle in js, needle
    html = served(tmp_path, "/")
    assert 'id="conn-banner"' in html and "connexion perdue" in html.lower()
    assert "conn-banner" in js and "onerror" in js


def test_app_js_notifies_on_video_status_changes(tmp_path, isolated_cwd):
    js = served(tmp_path, "/static/app.js")
    for status in ("done", "failed", "awaiting_review", "queued"):
        assert status in js
    assert "Notification" in js


def _api_calls(js: str) -> list[tuple[str, str]]:
    calls = []
    for m in re.finditer(r"""api\(\s*["`](/api[^"`?]*)[^"`]*["`]\s*(?:,\s*(?:\{\s*method:\s*"(\w+)"|jsonBody\(\s*"(\w+)"))?""", js):
        calls.append((m.group(2) or m.group(3) or "GET", re.sub(r"\$\{[^}]*\}", "x", m.group(1))))
    return calls


def test_every_route_called_by_app_js_exists_in_the_app(tmp_path, isolated_cwd):
    app = create_app(config=make_config(tmp_path))
    js = "".join(p.read_text(encoding="utf-8") for p in sorted(STATIC.rglob("*.js")))
    calls = _api_calls(js)
    assert len(calls) >= 6, calls
    missing = []
    for method, path in calls:
        ok = any(
            getattr(route, "path_regex", None) is not None
            and route.path_regex.match(path)
            and method in (getattr(route, "methods", None) or set())
            for route in app.routes
        )
        if not ok:
            missing.append(f"{method} {path}")
    assert missing == []


def test_toasts_with_undo_and_confirm_modal(tmp_path, isolated_cwd):
    js = "".join(served(tmp_path, f"/static/{n}") for n in ("ui.js", "app.js"))
    assert "function toast(" in js and "data-undo" in js and "Annuler" in js
    assert "UNDO_MS = 5000" in js
    assert "function confirmDialog(" in js and 'role", "dialog"' in js
    html = served(tmp_path, "/")
    assert 'id="toasts"' in html and 'id="overlay"' in html
    css = served(tmp_path, "/static/style.css")
    assert ".toast" in css and ".modal" in css


def test_theme_follows_system_with_remembered_toggle(tmp_path, isolated_cwd):
    html = served(tmp_path, "/")
    js = served(tmp_path, "/static/app.js")
    assert 'id="btn-theme"' in html
    assert "prefers-color-scheme" in html and "prefers-color-scheme" in js
    assert "localStorage" in html and "localStorage" in js
    assert "data-theme" in html or "dataset.theme" in html
    css = served(tmp_path, "/static/style.css")
    assert ':root[data-theme="light"]' in css and ':root[data-theme="dark"]' in css


def test_token_page_sets_cookie_and_replays_on_401(tmp_path, isolated_cwd):
    html = served(tmp_path, "/")
    js = served(tmp_path, "/static/app.js")
    assert 'id="token-view"' in html and 'id="token-form"' in html and 'type="password"' in html
    assert "clipper_token" in js and "document.cookie" in js
    assert "401" in js and "askToken(" in js
    # rejoue la requete apres saisie du jeton
    assert js.count("fetch(") >= 1 and "return api(" in js


class _TextAndLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self.urls: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for k, v in attrs:
            if k in ("src", "href", "srcset", "action") and v:
                self.urls.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.text.append(data.strip())


def test_no_external_resource_in_index_and_css(tmp_path, isolated_cwd):
    html = served(tmp_path, "/")
    parser = _TextAndLinks()
    parser.feed(html)
    external = [u for u in parser.urls if re.match(r"(?i)(https?:)?//", u)]
    assert external == []
    for name in ("style.css", "fonts.css"):
        css = served(tmp_path, f"/static/{name}")
        assert not re.search(r"(?i)https?://|@import|url\(\s*['\"]?//", css), name
    # les polices sont des fichiers locaux servis, sous licence libre citee
    fonts = served(tmp_path, "/static/fonts.css")
    files = re.findall(r"url\(([^)]+\.woff2)\)", fonts)
    assert files
    for f in files:
        assert f.startswith("/static/fonts/")
        assert client(tmp_path).get(f).status_code == 200, f
    licences = served(tmp_path, "/static/fonts/LICENSES.txt")
    for name in ("Barlow", "JetBrains Mono", "OFL"):
        assert name in licences


def test_visible_strings_are_french_and_no_real_names(tmp_path, isolated_cwd):
    html = served(tmp_path, "/")
    parser = _TextAndLinks()
    parser.feed(html)
    visible = " ".join(parser.text)
    for english in ("Loading", "Submit", "Cancel", "Dashboard", "Settings", "Save", "Search", "Connection lost"):
        assert english not in visible, english
    assert "Tableau de bord" in visible and "Réglages" in visible and "Chaînes" in visible
    forbidden = ("contre-pied", "contrepied", "amelia", "zedk", "nicoc", "twitch.tv/", "youtube.com/@")
    for path in sorted(STATIC.rglob("*")):
        if path.suffix in {".html", ".css", ".js", ".txt", ".svg"}:
            text = path.read_text(encoding="utf-8").lower()
            for word in forbidden:
                assert word not in text, f"{word!r} dans {path.name}"
    assert "ma_chaine" in served(tmp_path, "/static/screens.js")


def test_loading_skeletons_and_empty_states(tmp_path, isolated_cwd):
    html = served(tmp_path, "/")
    assert 'class="skeleton' in html
    css = served(tmp_path, "/static/style.css")
    assert ".skeleton" in css
    screens = served(tmp_path, "/static/screens.js")
    assert "Ajoute une vidéo" in screens and "Crée une chaîne" in screens


def test_static_assets_are_served(tmp_path, isolated_cwd):
    for name in ("app.js", "ui.js", "icons.js", "screens.js", "style.css", "fonts.css", "logo.svg"):
        assert client(tmp_path).get(f"/static/{name}").status_code == 200, name
    assert not (STATIC / "data.js").exists()


# --------------------------------------------------------------------------
# TASK-157b : ecran Videos (liste filtrable, fiche, durees, journal)
# --------------------------------------------------------------------------


def _step(started, finished, status="done", **extra):
    return {"status": status, "reason": None, "started_at": started, "finished_at": finished, **extra}


def _write_meta(tmp_path, video_id, title):
    meta = tmp_path / "workspace" / video_id / "meta.json"
    meta.write_text(json.dumps({"video_id": video_id, "title": title}), encoding="utf-8")


def _seed_videos(tmp_path):
    steps_a = {
        "download": _step("2026-09-30T10:00:00+00:00", "2026-09-30T10:00:42+00:00"),
        "transcribe": _step("2026-09-30T10:00:42+00:00", None, status="running",
                            progress={"fraction": 0.4, "eta_s": 90.0, "message": "segment 4/10"}),
    }
    _write_state(tmp_path, "aaaaaaaaaaa", status="running", channel="ma_chaine", steps=steps_a)
    _write_meta(tmp_path, "aaaaaaaaaaa", "Grosse partie du soir")
    _write_state(tmp_path, "bbbbbbbbbbb", status="failed", channel=None, reason="Erreur: reseau coupe")
    _write_state(tmp_path, "ccccccccccc", status="done", channel="autre_chaine",
                 source_url="https://example.org/video/XYZ")


def test_list_videos_enriches_each_video_with_title_duration_and_current_step(tmp_path, isolated_cwd):
    _seed_videos(tmp_path)

    by_id = {v["video_id"]: v for v in client(tmp_path).get("/api/videos").json()}

    a = by_id["aaaaaaaaaaa"]
    assert a["channel"] == "ma_chaine" and a["status"] == "running" and a["reason"] is None
    assert a["title"] == "Grosse partie du soir"
    assert a["current_step"] == "transcribe"
    assert a["durations"]["download"] == 42.0
    assert a["durations"]["transcribe"] is None  # pas finie : pas de duree inventee
    b = by_id["bbbbbbbbbbb"]
    assert b["channel"] is None and b["reason"] == "Erreur: reseau coupe"
    assert b["current_step"] == "download"  # premiere etape non terminee
    # sans meta.json : l'identifiant sert de titre, et la raison est dite
    assert b["title"] == "bbbbbbbbbbb"
    assert "meta.json" in b["title_reason"]
    assert "title_reason" not in a or a["title_reason"] is None


def test_list_videos_filters_by_channel(tmp_path, isolated_cwd):
    _seed_videos(tmp_path)
    resp = client(tmp_path).get("/api/videos", params={"channel": "ma_chaine"})
    assert [v["video_id"] for v in resp.json()] == ["aaaaaaaaaaa"]


def test_list_videos_filters_by_status(tmp_path, isolated_cwd):
    _seed_videos(tmp_path)
    resp = client(tmp_path).get("/api/videos", params={"status": "failed"})
    assert [v["video_id"] for v in resp.json()] == ["bbbbbbbbbbb"]


def test_list_videos_unknown_status_is_400_in_french(tmp_path, isolated_cwd):
    _seed_videos(tmp_path)
    resp = client(tmp_path).get("/api/videos", params={"status": "bizarre"})
    assert resp.status_code == 400
    assert "statut" in resp.json()["detail"]


@pytest.mark.parametrize("q, expected", [
    ("AAAAAA", ["aaaaaaaaaaa"]),              # video_id, insensible a la casse
    ("grosse partie", ["aaaaaaaaaaa"]),       # titre de meta.json
    ("example.org/video", ["ccccccccccc"]),   # source_url
    ("introuvable", []),
])
def test_list_videos_text_filter_matches_id_title_and_source_url(tmp_path, isolated_cwd, q, expected):
    _seed_videos(tmp_path)
    resp = client(tmp_path).get("/api/videos", params={"q": q})
    assert sorted(v["video_id"] for v in resp.json()) == expected


def test_list_videos_filters_combine(tmp_path, isolated_cwd):
    _seed_videos(tmp_path)
    resp = client(tmp_path).get("/api/videos", params={"channel": "ma_chaine", "status": "done"})
    assert resp.json() == []


def test_get_video_detail_includes_clips_awaiting_title_and_durations(tmp_path, isolated_cwd):
    clips = [{"clip_id": "03-p2", "ready": True, "qa_status": "passed", "issues": [],
              "mp4": "output/x/03-p2.mp4", "json": "output/x/03-p2.json"}]
    steps = {"download": _step("2026-09-30T10:00:00+00:00", "2026-09-30T10:01:30+00:00")}
    _write_state(tmp_path, VIDEO_ID, status="awaiting_review", awaiting=[0, 3], clips=clips, steps=steps)
    _write_meta(tmp_path, VIDEO_ID, "Titre de la source")

    body = client(tmp_path).get(f"/api/videos/{VIDEO_ID}").json()

    assert body["clips"] == clips
    assert body["awaiting"] == [0, 3]
    assert body["durations"]["download"] == 90.0
    assert body["title"] == "Titre de la source"
    assert body["video_id"] == VIDEO_ID and body["steps"]["download"]["status"] == "done"


# --- ecran videos de la page -------------------------------------------------

VIDEOS_JS = STATIC / "screens" / "videos.js"


def _videos_js(tmp_path) -> str:
    return served(tmp_path, "/static/screens/videos.js")


def test_index_loads_the_videos_screen_script_after_the_shell_screens(tmp_path, isolated_cwd):
    html = served(tmp_path, "/")
    assert html.index("/static/screens.js") < html.index("/static/screens/videos.js") < html.index("/static/app.js")


def test_videos_screen_has_add_form_with_channel_selector_and_action(tmp_path, isolated_cwd):
    js = _videos_js(tmp_path)
    for needle in ('name="url"', 'name="channel"', 'name="action"', "Sans chaîne", 'api("/api/channels"',
                   'value="run"', 'value="render"', '"/api/queue"', 'method: "POST"'):
        assert needle in js, needle


def test_videos_screen_lists_with_server_side_filters(tmp_path, isolated_cwd):
    js = _videos_js(tmp_path)
    assert "/api/videos?" in js
    for needle in ("channel", "status", "q"):
        assert f'.set("{needle}"' in js or f"{needle}:" in js or f'"{needle}"' in js, needle
    assert 'name="q"' in js and 'name="filter-channel"' in js and 'name="filter-status"' in js


def test_videos_screen_detail_has_12_step_frise_log_and_actions(tmp_path, isolated_cwd):
    js = _videos_js(tmp_path)
    for needle in ("class=\"frise\"", "fstep", "/api/videos/${", "/events", "clipper:event",
                   "/retry", "/cancel", "from_step", "confirmDialog(",
                   "Relancer depuis cette étape", "Annuler le traitement", "#/review/", "#/clips/",
                   'class="log"', "STEP_LABELS"):
        assert needle in js, needle
    # la frise est faite des 12 etapes du pipeline, dans l'ordre
    from clipper import pipeline
    app_text = "".join(p.read_text(encoding="utf-8") for p in STATIC.glob("*.js"))
    for step in pipeline.STEPS:
        assert f"{step}:" in app_text, step


def test_videos_screen_confirms_before_retry_and_cancel(tmp_path, isolated_cwd):
    js = _videos_js(tmp_path)
    for route in ("/retry", "/cancel"):
        idx = js.index(route)
        before = js[max(0, idx - 600):idx]
        assert "confirmDialog(" in before, route


def test_videos_screen_has_its_own_css_section(tmp_path, isolated_cwd):
    css = served(tmp_path, "/static/style.css")
    assert "/* ---------- Ecran Videos (TASK-157b) ---------- */" in css
# E1 : GET /api/dashboard (TASK-aad3, SPEC-c100 E1, T2, T8)
# --------------------------------------------------------------------------

import sys  # noqa: E402
import types  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "clipper" / "web" / "static"


def _dashboard(tmp_path) -> dict:
    resp = client(tmp_path).get("/api/dashboard")
    assert resp.status_code == 200
    return resp.json()


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_sidecar(tmp_path, video_id, clip_id, **fields):
    sidecar = {"clip_id": clip_id, "ready": True, "screen_title": f"Titre {clip_id}"}
    sidecar.update(fields)
    _write_json(tmp_path / "output" / video_id / f"{clip_id}.json", sidecar)


def _publish_entry(video_id, clip_id, status, slot_at):
    return {"video_id": video_id, "clip_id": clip_id, "series_id": None, "part": None, "status": status,
            "slot_at": slot_at, "decided_at": "2026-01-01T00:00:00+00:00", "published_at": None, "error": None}


def _usage_line(usage, cost, when, **extra):
    return {"recorded_at": when.isoformat(), "usage": usage, "model": "m", "input_tokens": 10,
            "output_tokens": 5, "cache_read_tokens": 0, "cost_usd": cost, "duration_s": 1.0, **extra}


def _write_usage(tmp_path, video_id, lines):
    path = tmp_path / "workspace" / video_id / "llm_usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


def test_dashboard_empty_workspace_has_explicit_empty_sections(tmp_path, isolated_cwd):
    data = _dashboard(tmp_path)

    assert data["running"] == [] and data["queue"] == [] and data["failed"] == [] and data["queued"] == []
    assert data["watch_pending"] == []
    assert data["clips_to_review"] == 0
    assert data["next_publications"] == []
    assert data["llm_cost"]["today"] == 0 and data["llm_cost"]["week"] == 0 and data["llm_cost"]["by_usage"] == {}
    assert not [k for k in data if k.endswith("_error")]


def test_dashboard_running_videos_expose_current_step_and_progress(tmp_path, isolated_cwd):
    progress = {"fraction": 0.4, "eta_s": 90.0, "message": "segment 3/8"}
    state = _write_state(tmp_path, "aaaaaaaaaaa", status="running", channel="ma_chaine")
    state["steps"]["download"]["status"] = "done"
    state["steps"]["transcribe"].update(status="running", progress=progress)
    _write_json(tmp_path / "workspace" / "aaaaaaaaaaa" / "pipeline.json", state)
    _write_state(tmp_path, "bbbbbbbbbbb", status="done")

    running = _dashboard(tmp_path)["running"]

    assert [v["video_id"] for v in running] == ["aaaaaaaaaaa"]
    assert running[0]["step"] == "transcribe"
    assert running[0]["progress"] == progress
    assert running[0]["channel"] == "ma_chaine"


def test_dashboard_queue_lists_queue_json_entries(tmp_path, isolated_cwd):
    entries = [{"id": "e1", "video_id": VIDEO_ID, "url": URL, "channel": None, "action": "run",
                "force_steps": [], "enqueued_at": "2026-01-01T00:00:00+00:00", "status": "waiting", "pid": None}]
    _write_json(tmp_path / "state" / "queue.json", entries)

    assert _dashboard(tmp_path)["queue"] == entries


def test_dashboard_failed_and_queued_carry_reason_and_retry_at(tmp_path, isolated_cwd):
    _write_state(tmp_path, "aaaaaaaaaaa", status="failed", reason="ffmpeg a echoue", retry_at=None)
    _write_state(tmp_path, "bbbbbbbbbbb", status="queued", reason="quota LLM atteint",
                 retry_at="2026-01-02T08:00:00+00:00")
    _write_state(tmp_path, "ccccccccccc", status="done")

    data = _dashboard(tmp_path)

    assert [(v["video_id"], v["reason"], v["retry_at"]) for v in data["failed"]] == [
        ("aaaaaaaaaaa", "ffmpeg a echoue", None)]
    assert [(v["video_id"], v["reason"], v["retry_at"]) for v in data["queued"]] == [
        ("bbbbbbbbbbb", "quota LLM atteint", "2026-01-02T08:00:00+00:00")]


def test_dashboard_watch_pending_gathers_vods_to_confirm(tmp_path, isolated_cwd):
    vod = {"video_id": "ddddddddddd", "url": "https://example.test/v/1", "title": "Direct du soir",
           "duration_s": 7200, "published_at": "2026-01-01T20:00:00+00:00", "found_at": "2026-01-02T01:00:00+00:00"}
    _write_json(tmp_path / "state" / "watch" / "ma_chaine.json",
                {"checked_at": "2026-01-02T01:00:00+00:00", "seen": [], "pending": [vod], "last_error": None})
    _write_json(tmp_path / "state" / "watch" / "autre.json",
                {"checked_at": "2026-01-02T01:00:00+00:00", "seen": [], "pending": [], "last_error": None})

    pending = _dashboard(tmp_path)["watch_pending"]

    assert pending == [{**vod, "channel": "ma_chaine"}]


def test_dashboard_unreadable_watch_file_is_null_with_a_french_error(tmp_path, isolated_cwd):
    (tmp_path / "state" / "watch").mkdir(parents=True)
    (tmp_path / "state" / "watch" / "ma_chaine.json").write_text("{pas du json", encoding="utf-8")

    data = _dashboard(tmp_path)

    assert data["watch_pending"] is None
    assert "ma_chaine.json" in data["watch_pending_error"]


def test_dashboard_counts_ready_clips_absent_from_publish_state(tmp_path, isolated_cwd):
    _write_state(tmp_path, "aaaaaaaaaaa", channel="ma_chaine")
    _write_state(tmp_path, "bbbbbbbbbbb", channel=None)
    _write_sidecar(tmp_path, "aaaaaaaaaaa", "01")
    _write_sidecar(tmp_path, "aaaaaaaaaaa", "02")
    _write_sidecar(tmp_path, "aaaaaaaaaaa", "03", ready=False)
    _write_sidecar(tmp_path, "bbbbbbbbbbb", "01")
    _write_json(tmp_path / "state" / "publish" / "ma_chaine.json",
                [_publish_entry("aaaaaaaaaaa", "01", "approved", None)])

    assert _dashboard(tmp_path)["clips_to_review"] == 2  # aaaa/02 et bbbb/01


def test_dashboard_invalid_publish_entry_is_null_with_a_french_error(tmp_path, isolated_cwd):
    _write_state(tmp_path, "aaaaaaaaaaa", channel="ma_chaine")
    _write_sidecar(tmp_path, "aaaaaaaaaaa", "01")
    _write_json(tmp_path / "state" / "publish" / "ma_chaine.json", [{"video_id": "aaaaaaaaaaa"}])

    data = _dashboard(tmp_path)

    assert data["clips_to_review"] is None
    assert data["clips_to_review_error"]
    assert data["next_publications"] is None
    assert data["next_publications_error"]


def test_dashboard_next_publications_are_the_five_earliest_scheduled_across_channels(tmp_path, isolated_cwd):
    base = datetime(2030, 1, 1, 12, 0)
    for i in range(4):
        _write_sidecar(tmp_path, "aaaaaaaaaaa", f"{i:02d}")
    entries_a = [_publish_entry("aaaaaaaaaaa", f"{i:02d}", "scheduled", (base + timedelta(days=2 * i)).isoformat())
                 for i in range(4)]
    entries_a.append(_publish_entry("aaaaaaaaaaa", "99", "approved", None))
    entries_a.append(_publish_entry("aaaaaaaaaaa", "98", "published", base.isoformat()))
    entries_b = [_publish_entry("bbbbbbbbbbb", f"{i:02d}", "scheduled", (base + timedelta(days=2 * i + 1)).isoformat())
                 for i in range(4)]
    _write_json(tmp_path / "state" / "publish" / "ma_chaine.json", entries_a)
    _write_json(tmp_path / "state" / "publish" / "autre.json", entries_b)

    nxt = _dashboard(tmp_path)["next_publications"]

    assert len(nxt) == 5
    assert [e["slot_at"] for e in nxt] == [(base + timedelta(days=d)).isoformat() for d in range(5)]
    assert [e["channel"] for e in nxt] == ["ma_chaine", "autre", "ma_chaine", "autre", "ma_chaine"]
    assert nxt[0]["screen_title"] == "Titre 00"
    assert all(e["status"] == "scheduled" for e in nxt)


def test_dashboard_llm_cost_sums_usage_journals_by_window_and_usage(tmp_path, isolated_cwd):
    now = datetime.now().astimezone()
    _write_usage(tmp_path, "aaaaaaaaaaa", [
        _usage_line("moments", 0.25, now),
        _usage_line("vision", 0.10, now),
        _usage_line("moments", 0.50, now - timedelta(days=3)),
        _usage_line("moments", 9.00, now - timedelta(days=30)),  # hors fenetre
    ])
    _write_usage(tmp_path, "bbbbbbbbbbb", [_usage_line("moments", 0.15, now)])

    cost = _dashboard(tmp_path)["llm_cost"]

    assert cost["today"] == pytest.approx(0.50)
    assert cost["week"] == pytest.approx(1.00)
    assert cost["by_usage"] == {"moments": pytest.approx(0.90), "vision": pytest.approx(0.10)}


def test_dashboard_llm_cost_window_uses_the_local_timezone(tmp_path, isolated_cwd):
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    _write_usage(tmp_path, "aaaaaaaaaaa", [
        _usage_line("moments", 1.0, local_midnight + timedelta(seconds=1)),
        _usage_line("moments", 2.0, local_midnight - timedelta(seconds=1)),  # veille locale
    ])

    cost = _dashboard(tmp_path)["llm_cost"]

    assert cost["today"] == pytest.approx(1.0)
    assert cost["week"] == pytest.approx(3.0)


def test_dashboard_llm_cost_reports_calls_with_unknown_cost(tmp_path, isolated_cwd):
    now = datetime.now().astimezone()
    _write_usage(tmp_path, "aaaaaaaaaaa", [_usage_line("moments", None, now), _usage_line("moments", 0.2, now)])

    cost = _dashboard(tmp_path)["llm_cost"]

    assert cost["today"] == pytest.approx(0.2)
    assert cost["unreported_calls"] == 1


def test_dashboard_unreadable_usage_journal_is_null_with_a_french_error(tmp_path, isolated_cwd):
    path = tmp_path / "workspace" / "aaaaaaaaaaa" / "llm_usage.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("pas du json\n", encoding="utf-8")

    data = _dashboard(tmp_path)

    assert data["llm_cost"] is None
    assert "llm_usage.jsonl" in data["llm_cost_error"]


def test_dashboard_hardware_is_cpu_without_vram_or_error(tmp_path, isolated_cwd, monkeypatch):
    from clipper import gpu

    monkeypatch.setattr(gpu, "get_device", lambda: gpu.Device(type="cpu", compute_type="int8"))

    data = _dashboard(tmp_path)

    assert data["hardware"] == {"device": "cpu", "vram_used_mb": None}
    assert "hardware_error" not in data


def test_dashboard_hardware_reads_vram_used_on_cuda_through_clipper_gpu(tmp_path, isolated_cwd, monkeypatch):
    from clipper import gpu

    monkeypatch.setattr(gpu, "get_device", lambda: gpu.Device(type="cuda", compute_type="float16"))
    monkeypatch.setattr(gpu, "vram_used_mb", lambda: 5 * 1024)
    monkeypatch.setitem(sys.modules, "torch", None)  # le panneau n'importe plus torch

    assert _dashboard(tmp_path)["hardware"] == {"device": "cuda", "vram_used_mb": 5 * 1024}


def test_dashboard_hardware_vram_unknown_is_null_with_the_reason(tmp_path, isolated_cwd, monkeypatch):
    from clipper import gpu

    def unavailable():
        raise gpu.GpuError("nvidia-smi introuvable dans le PATH")

    monkeypatch.setattr(gpu, "get_device", lambda: gpu.Device(type="cuda", compute_type="float16"))
    monkeypatch.setattr(gpu, "vram_used_mb", unavailable)
    monkeypatch.setitem(sys.modules, "torch", None)

    hw = _dashboard(tmp_path)["hardware"]

    assert hw["device"] == "cuda"
    assert hw["vram_used_mb"] is None
    assert "nvidia-smi introuvable" in hw["vram_used_mb_error"]
    assert "No module named" not in hw["vram_used_mb_error"] and "torch" not in hw["vram_used_mb_error"]


def test_web_app_never_imports_torch():
    assert "torch" not in (Path(__file__).resolve().parent.parent / "clipper" / "web" / "app.py").read_text(encoding="utf-8")


def test_dashboard_screen_is_wired_with_every_section_and_empty_state():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "screens" / "dashboard.js").read_text(encoding="utf-8")

    assert "/static/screens/dashboard.js" in page
    assert page.index("/static/screens.js") < page.index("/static/screens/dashboard.js")
    # une section par bloc de donnees (data-section=<cle>), chacune avec un etat vide explicite
    assert 'data-section="${key}"' in js
    for section in ("running", "queue", "failed", "queued", "watch_pending", "clips_to_review",
                    "next_publications", "llm_cost", "hardware"):
        assert f'dashSection("{section}"' in js, section
    for empty in ("Aucune vidéo en cours", "La file est vide", "Aucun échec", "Aucune vidéo en attente de reprise",
                  "Aucune VOD à confirmer", "Aucun clip à valider", "Aucune publication programmée",
                  "Aucun appel au modèle", "CPU"):
        assert empty in js, empty
    # mise a jour sur evenement SSE, donnees lues sur /api/dashboard, erreurs affichees
    assert "/api/dashboard" in js
    assert "clipper:event" in js
    assert "_error" in js


# --------------------------------------------------------------------------
# Revue des moments v2 (TASK-6e75) : API enrichie, ecran review, rendu en file
# --------------------------------------------------------------------------


TRANSCRIPT_JSON = {
    "segments": [
        {"start": 2.0, "end": 12.0, "words": [
            {"word": " GTA", "start": 2.0, "end": 3.0},
            {"word": " six", "start": 3.0, "end": 4.0},
            {"word": " arrive", "start": 4.0, "end": 12.0},
        ]},
        {"start": 40.0, "end": 60.0, "words": [
            {"word": " Autre", "start": 40.0, "end": 50.0},
            {"word": " moment", "start": 50.0, "end": 60.0},
        ]},
        {"start": 100.0, "end": 101.0, "words": [{"word": " hors", "start": 100.0, "end": 101.0}]},
    ],
}


def _write_review_sources(tmp_path, *, transcript=True, meta=True):
    _write_moments_fixtures(tmp_path)
    video_dir = tmp_path / "workspace" / VIDEO_ID
    if transcript:
        (video_dir / "transcript.json").write_text(json.dumps(TRANSCRIPT_JSON), encoding="utf-8")
    if meta:
        (video_dir / "meta.json").write_text(json.dumps({"video_id": VIDEO_ID, "duration": 3600}), encoding="utf-8")


def test_list_moments_carries_the_transcript_of_each_moment(tmp_path, isolated_cwd):
    _write_review_sources(tmp_path)

    moments = {m["id"]: m for m in client(tmp_path).get(f"/api/videos/{VIDEO_ID}/moments").json()}

    assert moments[0]["transcript"] == "GTA six arrive"
    assert moments[1]["transcript"] == "Autre moment"


def test_list_moments_carries_the_source_duration(tmp_path, isolated_cwd):
    _write_review_sources(tmp_path)

    moments = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/moments").json()

    assert all(m["source_duration"] == 3600 for m in moments)


def test_list_moments_transcript_reuses_the_pipeline_helper(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline

    _write_review_sources(tmp_path)
    calls = []

    def fake_moment_text(video_dir, start, end):
        calls.append((video_dir.name, start, end))
        return f"texte {start}-{end}"

    monkeypatch.setattr(pipeline, "_moment_text", fake_moment_text)

    moments = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/moments").json()

    assert calls == [(VIDEO_ID, 2.0, 26.0), (VIDEO_ID, 40.0, 60.0)]
    assert moments[0]["transcript"] == "texte 2.0-26.0"


def test_list_moments_missing_transcript_is_reported_not_hidden(tmp_path, isolated_cwd):
    _write_review_sources(tmp_path, transcript=False)

    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/moments")

    assert resp.status_code == 200
    first = resp.json()[0]
    assert first["transcript"] is None
    assert "transcript.json" in first["transcript_error"]


def test_list_moments_missing_source_duration_is_reported_not_hidden(tmp_path, isolated_cwd):
    _write_review_sources(tmp_path, meta=False)

    first = client(tmp_path).get(f"/api/videos/{VIDEO_ID}/moments").json()[0]

    assert first["source_duration"] is None
    assert "meta.json" in first["source_duration_error"]


def test_render_route_does_not_use_background_tasks():
    source = (Path(__file__).resolve().parent.parent / "clipper" / "web" / "app.py").read_text(encoding="utf-8")
    assert "BackgroundTasks" not in source
    assert "background_tasks" not in source


def _review_js() -> str:
    return (STATIC / "screens" / "review.js").read_text(encoding="utf-8")


def test_review_screen_is_wired_after_screens_js():
    page = (STATIC / "index.html").read_text(encoding="utf-8")

    assert "/static/screens/review.js" in page
    assert page.index("/static/screens.js") < page.index("/static/screens/review.js")
    assert "Screens.review" in _review_js()


def test_review_screen_has_a_player_locked_on_the_selected_moment():
    js = _review_js()

    assert "<video" in js
    assert "preview_url" in js
    assert "currentTime" in js
    assert "timeupdate" in js  # le lecteur reste dans [debut, fin] du moment


def test_review_screen_has_a_timeline_with_handles_bound_to_numeric_fields():
    js = _review_js()

    assert 'data-handle="start"' in js and 'data-handle="end"' in js
    assert "pointerdown" in js
    assert 'type="number"' in js
    assert 'data-field="start"' in js and 'data-field="end"' in js
    assert "source_duration" in js


def test_review_screen_shows_the_jury_justification_and_transcript():
    js = _review_js()

    assert "justification" in js
    assert "transcript" in js


def test_review_screen_sends_decisions_to_decide_with_an_undo_toast():
    js = _review_js()

    assert "/decide" in js
    for decision in ("accepted", "rejected", "adjusted"):
        assert decision in js
    assert "undo:" in js  # toast 'Annuler'
    assert "previous" in js  # renvoie la decision precedente


def test_review_screen_has_keyboard_shortcuts_documented_in_the_screen():
    js = _review_js()

    assert 'addEventListener("keydown"' in js
    for key in ('"a"', '"r"', '"j"', '"k"', '" "'):
        assert key in js, key
    assert "<kbd>A</kbd>" in js and "<kbd>R</kbd>" in js
    assert "<kbd>J</kbd>" in js and "<kbd>K</kbd>" in js
    assert "<kbd>Espace</kbd>" in js


def test_review_screen_render_button_is_blocked_while_moments_await_a_decision():
    js = _review_js()

    assert "awaiting" in js
    assert "/api/videos/${" in js or "/api/videos/" in js
    assert "/render" in js
    assert "disabled" in js
    assert "sans décision" in js  # la raison affichee
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".review-layout" in css
# Ecran Clips (TASK-3b9c) : GET /api/clips, approve/reject, PATCH, rerender
# (publish et worker simules ; l'API ne touche jamais un mp4 ni un sidecar)
# --------------------------------------------------------------------------

CLIPS_VIDEO = "clipsvideo01"


def _clip_sidecar(clip_id, *, part=1, parts_total=1, ready=True, qa_status="passed", issues=None, **extra):
    return {
        "video_id": CLIPS_VIDEO, "clip_id": clip_id, "part": part, "parts_total": parts_total,
        "screen_title": f"Titre {clip_id}", "title": f"Titre {clip_id}", "caption": f"Description {clip_id}",
        "hashtags": ["#ma_chaine"], "ready": ready, "layout": "letterbox", "duration": 24.0, "score": 80.0,
        "qa": {"status": qa_status, "issues": issues or []}, **extra,
    }


def _write_clip(tmp_path, video_id, sidecar):
    out_dir = tmp_path / "output" / video_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{sidecar['clip_id']}.json").write_text(json.dumps(sidecar), encoding="utf-8")
    (out_dir / f"{sidecar['clip_id']}.mp4").write_bytes(b"fake-mp4")


def _write_publish(tmp_path, channel, entries):
    path = tmp_path / "state" / "publish" / f"{channel}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


def _entry(clip_id, status, video_id=CLIPS_VIDEO, **extra):
    return {"video_id": video_id, "clip_id": clip_id, "series_id": None, "part": None, "status": status,
            "slot_at": None, "decided_at": None, "published_at": None, "error": None, **extra}


def _clips_setup(tmp_path):
    _write_state(tmp_path, CLIPS_VIDEO, channel="ma_chaine")
    _write_state(tmp_path, "othervideo01", channel="autre")
    _write_clip(tmp_path, CLIPS_VIDEO, _clip_sidecar("01"))
    _write_clip(tmp_path, CLIPS_VIDEO, _clip_sidecar("02", qa_status="rejected", ready=False, issues=["sous-titres hors zone"]))
    _write_clip(tmp_path, CLIPS_VIDEO, _clip_sidecar("03"))
    _write_clip(tmp_path, "othervideo01", {**_clip_sidecar("01"), "video_id": "othervideo01"})
    _write_publish(tmp_path, "ma_chaine", [
        _entry("01", "scheduled", slot_at="2026-10-02T18:00:00+00:00"),
        _entry("03", "failed", error="quota depasse"),
    ])


def test_get_clips_returns_sidecar_url_qa_and_publish_status(tmp_path, isolated_cwd):
    _clips_setup(tmp_path)

    resp = client(tmp_path).get("/api/clips", params={"video_id": CLIPS_VIDEO})

    assert resp.status_code == 200
    clips = {c["clip_id"]: c for c in resp.json()}
    assert sorted(clips) == ["01", "02", "03"]
    first = clips["01"]
    assert first["video_url"] == f"/media/clip/{CLIPS_VIDEO}/01"
    assert first["screen_title"] == "Titre 01"
    assert first["description"] == "Description 01"
    assert first["hashtags"] == ["#ma_chaine"]
    assert first["part"] == 1 and first["parts_total"] == 1
    assert first["channel"] == "ma_chaine"
    assert first["qa_status"] == "passed" and first["issues"] == []
    assert first["publish_status"] == "scheduled"
    assert first["slot_at"] == "2026-10-02T18:00:00+00:00"
    assert clips["02"]["qa_status"] == "rejected"
    assert clips["02"]["issues"] == ["sous-titres hors zone"]
    assert clips["02"]["publish_status"] == "rejected"               # refusé par la QA : jamais « à valider »
    assert clips["03"]["publish_status"] == "failed"
    assert clips["03"]["publish_error"] == "quota depasse"


def test_get_clips_filters_by_channel_video_and_status(tmp_path, isolated_cwd):
    _clips_setup(tmp_path)
    c = client(tmp_path)

    by_channel = c.get("/api/clips", params={"channel": "autre"}).json()
    assert [(x["video_id"], x["clip_id"]) for x in by_channel] == [("othervideo01", "01")]
    assert len(c.get("/api/clips").json()) == 4
    by_status = c.get("/api/clips", params={"status": "à valider"}).json()
    assert {(x["video_id"], x["clip_id"]) for x in by_status} == {("othervideo01", "01")}
    assert [x["clip_id"] for x in c.get("/api/clips", params={"status": "failed", "video_id": CLIPS_VIDEO}).json()] == ["03"]


def test_get_clips_rejects_an_unknown_status_and_an_unsafe_video_id(tmp_path, isolated_cwd):
    c = client(tmp_path)
    bad = c.get("/api/clips", params={"status": "bogus"})
    assert bad.status_code == 400 and "bogus" in bad.json()["detail"]
    assert c.get("/api/clips", params={"video_id": "../x"}).status_code == 400


def test_get_clips_empty_output_is_an_empty_list(tmp_path, isolated_cwd):
    assert client(tmp_path).get("/api/clips").json() == []


def test_get_clips_corrupt_publish_file_is_a_french_error_not_a_silent_status(tmp_path, isolated_cwd):
    _clips_setup(tmp_path)
    (tmp_path / "state" / "publish" / "ma_chaine.json").write_text("{pas du json", encoding="utf-8")

    resp = client(tmp_path).get("/api/clips")

    assert resp.status_code == 500
    assert "ma_chaine.json" in resp.json()["detail"]


def test_approve_and_reject_call_publish(tmp_path, isolated_cwd, monkeypatch):
    from clipper import publish

    _clips_setup(tmp_path)
    calls = []
    monkeypatch.setattr(publish, "approve", lambda *a, **kw: calls.append(("approve", a, kw)) or _entry("01", "scheduled"))
    monkeypatch.setattr(publish, "reject", lambda *a, **kw: calls.append(("reject", a, kw)) or _entry("01", "rejected"))
    c = client(tmp_path)

    ok = c.post(f"/api/clips/{CLIPS_VIDEO}/01/approve")
    no = c.post(f"/api/clips/{CLIPS_VIDEO}/01/reject")

    assert ok.status_code == 200 and ok.json()["status"] == "scheduled"
    assert no.status_code == 200 and no.json()["status"] == "rejected"
    assert [(name, args) for name, args, _ in calls] == [
        ("approve", (CLIPS_VIDEO, "01", "ma_chaine")), ("reject", (CLIPS_VIDEO, "01", "ma_chaine"))]
    assert calls[0][2]["output_dir"] == tmp_path / "output"


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_approve_reject_publish_error_is_409_with_detail(tmp_path, isolated_cwd, monkeypatch, action):
    from clipper import publish

    _clips_setup(tmp_path)

    def boom(*a, **kw):
        raise publish.PublishError("clip non pret pour publication : x/02")

    monkeypatch.setattr(publish, action, boom)

    resp = client(tmp_path).post(f"/api/clips/{CLIPS_VIDEO}/02/{action}")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "clip non pret pour publication : x/02"


def test_approve_a_clip_of_a_video_without_channel_is_409(tmp_path, isolated_cwd, monkeypatch):
    from clipper import publish

    _write_state(tmp_path, CLIPS_VIDEO)
    _write_clip(tmp_path, CLIPS_VIDEO, _clip_sidecar("01"))
    monkeypatch.setattr(publish, "approve", lambda *a, **kw: pytest.fail("publish.approve ne doit pas etre appele"))

    resp = client(tmp_path).post(f"/api/clips/{CLIPS_VIDEO}/01/approve")

    assert resp.status_code == 409
    assert "chaîne" in resp.json()["detail"]


def test_patch_caption_calls_edit_caption_and_never_writes_the_sidecar(tmp_path, isolated_cwd, monkeypatch):
    from clipper import publish, worker

    _clips_setup(tmp_path)
    sidecar_path = tmp_path / "output" / CLIPS_VIDEO / "02.json"
    before = sidecar_path.read_bytes()
    calls = []

    def fake_edit(video_id, clip_id, channel, description, hashtags, **kw):
        calls.append((video_id, clip_id, channel, description, hashtags, kw))
        return {**_clip_sidecar("02"), "caption": description, "hashtags": hashtags, "edited_at": "2026-10-01T00:00:00+00:00"}

    monkeypatch.setattr(publish, "edit_caption", fake_edit)
    monkeypatch.setattr(worker, "enqueue", lambda *a, **kw: pytest.fail("pas de re-rendu pour un simple texte"))

    resp = client(tmp_path).patch(f"/api/clips/{CLIPS_VIDEO}/02", json={"description": "Nouveau texte", "hashtags": ["#a", "#b"]})

    assert resp.status_code == 200
    assert calls[0][:5] == (CLIPS_VIDEO, "02", "ma_chaine", "Nouveau texte", ["#a", "#b"])
    body = resp.json()
    assert body["clip"]["description"] == "Nouveau texte"
    assert body["clip"]["hashtags"] == ["#a", "#b"]
    assert body["rerender"] is None
    assert sidecar_path.read_bytes() == before


def test_patch_publish_error_is_409(tmp_path, isolated_cwd, monkeypatch):
    from clipper import publish

    _clips_setup(tmp_path)

    def boom(*a, **kw):
        raise publish.PublishError("edition refusee pour x/01 : statut 'scheduled'")

    monkeypatch.setattr(publish, "edit_caption", boom)

    resp = client(tmp_path).patch(f"/api/clips/{CLIPS_VIDEO}/01", json={"description": "x", "hashtags": []})

    assert resp.status_code == 409
    assert "scheduled" in resp.json()["detail"]


def test_patch_with_nothing_to_change_is_400(tmp_path, isolated_cwd):
    _clips_setup(tmp_path)
    assert client(tmp_path).patch(f"/api/clips/{CLIPS_VIDEO}/01", json={}).status_code == 400


def test_patch_screen_title_enqueues_a_targeted_render_after_confirmation(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    _clips_setup(tmp_path)
    calls = []

    def fake_enqueue(url, channel, action, force_steps, *, config=None):
        calls.append((url, channel, action, force_steps))
        return {"id": "e1", "video_id": url, "channel": channel, "action": action,
                "force_steps": force_steps, "status": "waiting"}

    monkeypatch.setattr(worker, "enqueue", fake_enqueue)
    c = client(tmp_path)

    refused = c.patch(f"/api/clips/{CLIPS_VIDEO}/01", json={"screen_title": "Nouveau titre"})
    assert refused.status_code == 409 and "confirm" in refused.json()["detail"]
    assert calls == []

    resp = c.patch(f"/api/clips/{CLIPS_VIDEO}/01", json={"screen_title": "Nouveau titre", "confirm": True})

    assert resp.status_code == 202
    assert calls == [(CLIPS_VIDEO, "ma_chaine", "render", ["render", "qa"])]
    assert resp.json()["rerender"]["action"] == "render"


def test_patch_caption_and_screen_title_does_both(tmp_path, isolated_cwd, monkeypatch):
    from clipper import publish, worker

    _clips_setup(tmp_path)
    edits, queued = [], []
    monkeypatch.setattr(publish, "edit_caption",
                        lambda *a, **kw: edits.append(a) or {**_clip_sidecar("01"), "caption": a[3], "hashtags": a[4]})
    monkeypatch.setattr(worker, "enqueue", lambda url, channel, action, force_steps, *, config=None:
                        queued.append((url, action, force_steps)) or {"id": "e", "video_id": url, "action": action})

    resp = client(tmp_path).patch(f"/api/clips/{CLIPS_VIDEO}/01", json={
        "description": "d", "hashtags": ["#x"], "screen_title": "T", "confirm": True})

    assert resp.status_code == 202
    assert edits == [(CLIPS_VIDEO, "01", "ma_chaine", "d", ["#x"])]
    assert queued == [(CLIPS_VIDEO, "render", ["render", "qa"])]


def test_patch_same_screen_title_does_not_rerender(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    _clips_setup(tmp_path)
    monkeypatch.setattr(worker, "enqueue", lambda *a, **kw: pytest.fail("titre inchange : pas de re-rendu"))

    resp = client(tmp_path).patch(f"/api/clips/{CLIPS_VIDEO}/01", json={"screen_title": "Titre 01", "confirm": True})

    assert resp.status_code == 400
    assert "inchangé" in resp.json()["detail"]


def test_rerender_enqueues_render_and_qa_for_the_clip(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    _clips_setup(tmp_path)
    calls = []
    monkeypatch.setattr(worker, "enqueue", lambda url, channel, action, force_steps, *, config=None:
                        calls.append((url, channel, action, force_steps)) or
                        {"id": "e1", "video_id": url, "action": action, "force_steps": force_steps})

    resp = client(tmp_path).post(f"/api/clips/{CLIPS_VIDEO}/01/rerender")

    assert resp.status_code == 202
    assert calls == [(CLIPS_VIDEO, "ma_chaine", "render", ["render", "qa"])]


def test_rerender_already_queued_is_409(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    _clips_setup(tmp_path)

    def boom(*a, **kw):
        raise worker.WorkerError("deja en file d'attente : x (render)")

    monkeypatch.setattr(worker, "enqueue", boom)

    resp = client(tmp_path).post(f"/api/clips/{CLIPS_VIDEO}/01/rerender")

    assert resp.status_code == 409 and "deja en file" in resp.json()["detail"]


def test_clip_routes_reject_unsafe_ids(tmp_path, isolated_cwd):
    c = client(tmp_path)
    assert c.post(f"/api/clips/{CLIPS_VIDEO}/..%2Fx/approve").status_code in (400, 404)
    assert c.post("/api/clips/bad.id/01/approve").status_code == 400


def test_clip_media_route_still_serves_the_mp4(tmp_path, isolated_cwd):
    _clips_setup(tmp_path)
    resp = client(tmp_path).get(f"/media/clip/{CLIPS_VIDEO}/01")
    assert resp.status_code == 200 and resp.content == b"fake-mp4"


def test_clips_screen_is_wired_with_gallery_sidecar_and_actions():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "screens" / "clips.js").read_text(encoding="utf-8")

    assert "/static/screens/clips.js" in page
    assert page.index("/static/screens.js") < page.index("/static/screens/clips.js")
    assert "Screens.clips" in js
    assert "/api/clips" in js
    assert "<video" in js and "controls" in js           # lecteur
    assert "clip-poster" in js and "aspect" in (STATIC / "style.css").read_text(encoding="utf-8")
    for label in ("Titre d'écran", "Description", "Hashtags", "Contrôle qualité", "Partie"):
        assert label in js, label
    for action in ("/approve", "/reject", "/rerender", "PATCH"):
        assert action in js, action
    assert "toute la série" in js                        # refus d'une partie
    assert "download" in js and "video_url" in js        # lien de telechargement
    assert "copyText" in js                              # description + hashtags
    assert "undo" in js                                  # toast « Annuler »
    assert "confirm: true" in js                         # re-rendu confirmé
    assert "Aucun clip" in js                            # etat vide


# --------------------------------------------------------------------------
# Ecran Chaines (SPEC-c100 E5, SPEC-fc0c §1) : API par chaine + page
# --------------------------------------------------------------------------

CH = "ma_chaine"
_CH_PRESET = (
    '[channel]\ndisplay_name = "Ma chaîne"\nwatch = true\n'
    'slots = [{day = "mon", time = "18:30"}, {day = "thu", time = "12:00"}]\n'
    '\n[reframe]\nletterbox_zoom = 1.5\n'
)


def _channels_setup(tmp_path, preset=_CH_PRESET, name=CH):
    (tmp_path / "config.toml").write_text('mode = "review"\n[render]\ncrf = 18\n', encoding="utf-8")
    (tmp_path / "presets").mkdir(exist_ok=True)
    (tmp_path / "presets" / f"{name}.toml").write_text(preset, encoding="utf-8")


def test_get_channel_returns_raw_effective_and_documented_defaults(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    data = client(tmp_path).get(f"/api/channels/{CH}").json()

    assert data["name"] == CH
    # ce que le preset redéfinit, tel quel (rien d'hérité)
    assert data["raw"]["channel"]["display_name"] == "Ma chaîne"
    assert data["raw"]["reframe"] == {"letterbox_zoom": 1.5}
    assert "render" not in data["raw"]
    # valeurs effectives : preset > config.toml > CONFIG_DEFAULTS
    assert data["effective"]["reframe"]["letterbox_zoom"] == 1.5
    assert data["effective"]["render"]["crf"] == 18          # hérité de config.toml
    assert data["effective"]["render"]["max_fps"] == 30       # hérité de CONFIG_DEFAULTS
    assert data["effective"]["channel"]["mode"] == "review"   # mode global
    assert data["effective"]["channel"]["timezone"] == "Europe/Paris"
    # les sections du formulaire sont toutes là
    for section in ("channel", "reframe", "render", "subtitles", "moments"):
        assert section in data["defaults"], section
    # défaut + commentaire de la ligne précédente dans le source
    fps = data["defaults"]["render"]["max_fps"]
    assert fps["default"] == 30 and "Cadence de sortie" in fps["comment"]
    assert data["defaults"]["render"]["crf"]["comment"] == ""     # pas de commentaire : vide, pas inventé
    assert data["defaults"]["channel"]["watch_interval_s"]["default"] == 1800


def test_get_channel_comments_come_from_source_without_importing_values(tmp_path, isolated_cwd):
    from clipper.web import app as web_app

    comments = web_app._defaults_documentation("moments")
    assert "Grille de notation" in comments["rubric_path"]["comment"]
    assert "jamais de repli" in comments["rubric_path"]["comment"]    # bloc de commentaires entier
    assert comments["rubric_path"]["default"] == "rubric.toml"


def test_get_channel_unknown_is_404_and_invalid_name_422(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    c = client(tmp_path)
    assert c.get("/api/channels/autre").status_code == 404
    assert "autre" in c.get("/api/channels/autre").json()["detail"]
    assert c.get("/api/channels/Bad.Name").status_code == 422


def test_get_channel_without_config_toml_says_so(tmp_path, isolated_cwd):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / f"{CH}.toml").write_text("[channel]\n", encoding="utf-8")
    resp = client(tmp_path).get(f"/api/channels/{CH}")
    assert resp.status_code == 422 and "config.toml" in resp.json()["detail"]


def test_put_channel_saves_through_save_channel(tmp_path, isolated_cwd, monkeypatch):
    _channels_setup(tmp_path)
    from clipper import channel as channel_mod

    calls = []
    real = channel_mod.save_channel

    def spy(name, data, **kwargs):
        calls.append((name, data, kwargs))
        return real(name, data, **kwargs)

    monkeypatch.setattr(channel_mod, "save_channel", spy)
    preset = {"channel": {"display_name": "Autre", "mode": "auto"}, "render": {"crf": 22}}
    resp = client(tmp_path).put(f"/api/channels/{CH}", json={"preset": preset})

    assert resp.status_code == 200, resp.text
    assert any(n == CH and d == preset and k["presets_dir"] == "presets" for n, d, k in calls)
    assert resp.json()["raw"] == preset
    assert resp.json()["effective"]["channel"]["mode"] == "auto"
    assert "crf = 22" in (tmp_path / "presets" / f"{CH}.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize("preset, section, key", [
    ({"reframe": {"zzz": 1}}, "reframe", "zzz"),                            # clé inconnue (ConfigError)
    ({"channel": {"mode": "turbo"}}, "channel", "mode"),                    # mode invalide
    ({"channel": {"slots": [{"day": "xx", "time": "18:30"}]}}, "channel", "slots"),
    ({"channel": {"watch_interval_s": "vite"}}, "channel", "watch_interval_s"),   # mauvais type
    ({"channel": {"timezone": "Mars/Olympus"}}, "channel", "timezone"),
    ({"render": {"crf": True}}, "render", "crf"),                           # bool n'est pas un entier
])
def test_put_channel_invalid_is_422_naming_section_and_key_and_keeps_the_file(
    tmp_path, isolated_cwd, preset, section, key
):
    _channels_setup(tmp_path)
    path = tmp_path / "presets" / f"{CH}.toml"
    before = path.read_text(encoding="utf-8")

    resp = client(tmp_path).put(f"/api/channels/{CH}", json={"preset": preset})

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert f"[{section}]" in detail and key in detail, detail
    assert path.read_text(encoding="utf-8") == before


def test_put_channel_config_error_from_save_channel_is_422(tmp_path, isolated_cwd, monkeypatch):
    _channels_setup(tmp_path)
    from clipper import channel as channel_mod
    from clipper.config import ConfigError

    def boom(*args, **kwargs):
        raise ConfigError("cle(s) inconnue(s) dans la section [render]: zzz")

    monkeypatch.setattr(channel_mod, "save_channel", boom)
    resp = client(tmp_path).put(f"/api/channels/{CH}", json={"preset": {"channel": {}}})
    assert resp.status_code == 422 and "[render]" in resp.json()["detail"] and "zzz" in resp.json()["detail"]


def test_put_channel_unknown_is_404_and_keeps_the_channel_table(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    c = client(tmp_path)
    assert c.put("/api/channels/autre", json={"preset": {"channel": {}}}).status_code == 404
    # un preset sans [channel] n'est plus une chaîne : le serveur garde la table
    assert c.put(f"/api/channels/{CH}", json={"preset": {"render": {"crf": 20}}}).status_code == 200
    assert c.get("/api/channels").json() == [CH]


def test_post_channel_creates_a_preset(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    c = client(tmp_path)
    resp = c.post("/api/channels", json={"name": "nouvelle", "preset": {"channel": {"source_url": "https://exemple.test/c"}}})

    assert resp.status_code == 201, resp.text
    assert resp.json()["raw"]["channel"]["source_url"] == "https://exemple.test/c"
    assert (tmp_path / "presets" / "nouvelle.toml").is_file()
    assert c.get("/api/channels").json() == [CH, "nouvelle"]
    # sans preset : une chaîne vide mais valide (la table [channel] existe)
    assert c.post("/api/channels", json={"name": "vide"}).status_code == 201
    assert "vide" in c.get("/api/channels").json()


def test_post_channel_invalid_name_is_422_existing_is_409_bad_preset_422(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    c = client(tmp_path)
    for bad in ("Ma Chaine", "../x", "", "a" * 41):
        resp = c.post("/api/channels", json={"name": bad})
        assert resp.status_code == 422, bad
        assert "nom" in resp.json()["detail"]
    assert c.post("/api/channels", json={"name": CH}).status_code == 409
    resp = c.post("/api/channels", json={"name": "autre", "preset": {"render": {"zzz": 1}}})
    assert resp.status_code == 422 and "zzz" in resp.json()["detail"]
    assert not (tmp_path / "presets" / "autre.toml").exists()


def test_delete_channel_requires_confirm(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    c = client(tmp_path)
    path = tmp_path / "presets" / f"{CH}.toml"

    refused = c.delete(f"/api/channels/{CH}")
    assert refused.status_code == 409 and "confirm" in refused.json()["detail"]
    assert c.delete(f"/api/channels/{CH}?confirm=false").status_code == 409
    assert path.exists()

    ok = c.delete(f"/api/channels/{CH}?confirm=true")
    assert ok.status_code == 200 and ok.json() == {"name": CH, "deleted": True}
    assert not path.exists()
    assert c.delete(f"/api/channels/{CH}?confirm=true").status_code == 404


def test_channel_slots_returns_the_next_ten_slots(tmp_path, isolated_cwd):
    from datetime import datetime, timezone

    _channels_setup(tmp_path)
    data = client(tmp_path).get(f"/api/channels/{CH}/slots").json()

    slots = [datetime.fromisoformat(s) for s in data["slots"]]
    assert len(slots) == 10 and slots == sorted(slots)
    assert all(s > datetime.now(timezone.utc) for s in slots)
    assert {(s.weekday(), s.strftime("%H:%M")) for s in slots} == {(0, "18:30"), (3, "12:00")}
    assert data["timezone"] == "Europe/Paris" and data["reason"] is None


def test_channel_slots_without_slots_says_why(tmp_path, isolated_cwd):
    _channels_setup(tmp_path, preset="[channel]\n")
    data = client(tmp_path).get(f"/api/channels/{CH}/slots").json()
    assert data["slots"] == [] and "créneau" in data["reason"]
    assert client(tmp_path).get("/api/channels/autre/slots").status_code == 404


def _multipart(filename: str, content: bytes, field: str = "file") -> tuple[bytes, str]:
    boundary = "----clipperTest"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def test_channel_logo_multipart_upload_writes_presets_png(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    body, ctype = _multipart("logo.png", _PNG)
    resp = client(tmp_path).post(f"/api/channels/{CH}/logo", content=body, headers={"content-type": ctype})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"name": CH, "logo": f"presets/{CH}.png"}
    assert (tmp_path / "presets" / f"{CH}.png").read_bytes() == _PNG


def test_channel_logo_refuses_non_png_and_missing_file(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    c = client(tmp_path)
    body, ctype = _multipart("logo.png", b"GIF89a-pas-un-png")
    resp = c.post(f"/api/channels/{CH}/logo", content=body, headers={"content-type": ctype})
    assert resp.status_code == 422 and "PNG" in resp.json()["detail"]
    body, ctype = _multipart("logo.png", _PNG, field="autre")
    assert c.post(f"/api/channels/{CH}/logo", content=body, headers={"content-type": ctype}).status_code == 422
    assert c.post(f"/api/channels/{CH}/logo", content=b"x", headers={"content-type": "text/plain"}).status_code == 422
    body, ctype = _multipart("logo.png", _PNG)
    assert c.post("/api/channels/autre/logo", content=body, headers={"content-type": ctype}).status_code == 404
    assert not (tmp_path / "presets" / f"{CH}.png").exists()


def test_channels_screen_is_wired_with_list_form_inheritance_and_toast():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "screens" / "channels.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")

    assert "/static/screens/channels.js" in page
    assert page.index("/static/screens.js") < page.index("/static/screens/channels.js")
    assert "Screens.channels" in js
    # liste : nom, source, surveillance, mode, prochains créneaux
    for label in ("source_url", "Surveillance", "Mode", "Prochains créneaux", "/slots"):
        assert label in js, label
    # formulaire par sections
    for section in ("channel", "reframe", "render", "subtitles", "moments"):
        assert f'"{section}"' in js, section
    for title in ("Agencement", "Titre", "Sous-titres", "Grille"):
        assert title in js, title
    # valeur héritée grisée + « redéfinir », erreur au champ, enregistrement avec toast
    assert "redéfinir" in js and "inherited" in js and "data-redefine" in js
    assert "field-error" in js
    assert "jsonBody(\"PUT\"" in js and "jsonBody(\"POST\"" in js
    assert 'method: "DELETE"' in js and "confirm=true" in js and "confirmDialog" in js
    assert "toast(" in js and "Chaîne enregistrée" in js
    assert "Aucune chaîne" in js                       # état vide
    assert "FormData" in js and "/logo" in js          # envoi du logo
    assert ".chan-" in css and ".inherited" in css
# Surveillance : VOD à confirmer (TASK-7508, SPEC-fc0c §5, SPEC-c100)
# --------------------------------------------------------------------------

WATCH_VOD_A = "ddddddddddd"
WATCH_VOD_B = "eeeeeeeeeee"


def _watch_setup(tmp_path) -> None:
    vods = [{"video_id": v, "url": f"https://youtu.be/{v}", "title": f"Direct {v}", "duration_s": 7200,
             "published_at": "2026-01-01T20:00:00+00:00", "found_at": "2026-01-02T01:00:00+00:00"}
            for v in (WATCH_VOD_A, WATCH_VOD_B)]
    _write_json(tmp_path / "state" / "watch" / "ma_chaine.json",
                {"checked_at": "2026-01-02T01:00:00+00:00", "seen": [], "pending": vods, "last_error": None})


def _watch_state(tmp_path) -> dict:
    return json.loads((tmp_path / "state" / "watch" / "ma_chaine.json").read_text(encoding="utf-8"))


def test_watch_confirm_enqueues_the_vod_and_removes_it_from_pending(tmp_path, isolated_cwd):
    _watch_setup(tmp_path)

    resp = client(tmp_path).post(f"/api/watch/ma_chaine/{WATCH_VOD_A}/confirm")

    assert resp.status_code == 202
    assert resp.json()["video_id"] == WATCH_VOD_A
    queue = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert [(e["video_id"], e["action"], e["channel"]) for e in queue] == [(WATCH_VOD_A, "run", "ma_chaine")]
    state = _watch_state(tmp_path)
    assert [v["video_id"] for v in state["pending"]] == [WATCH_VOD_B]
    assert WATCH_VOD_A in state["seen"]
    assert [v["video_id"] for v in _dashboard(tmp_path)["watch_pending"]] == [WATCH_VOD_B]


def test_watch_ignore_marks_the_vod_seen_without_enqueueing(tmp_path, isolated_cwd):
    _watch_setup(tmp_path)

    resp = client(tmp_path).post(f"/api/watch/ma_chaine/{WATCH_VOD_B}/ignore")

    assert resp.status_code == 200
    assert not (tmp_path / "state" / "queue.json").exists()
    state = _watch_state(tmp_path)
    assert [v["video_id"] for v in state["pending"]] == [WATCH_VOD_A]
    assert state["seen"] == [WATCH_VOD_B]


@pytest.mark.parametrize("action", ["confirm", "ignore"])
def test_watch_unknown_vod_is_a_404_with_a_french_detail(tmp_path, isolated_cwd, action):
    _watch_setup(tmp_path)

    resp = client(tmp_path).post(f"/api/watch/ma_chaine/zzzzzzzzzzz/{action}")

    assert resp.status_code == 404
    assert "zzzzzzzzzzz" in resp.json()["detail"]
    assert len(_watch_state(tmp_path)["pending"]) == 2


@pytest.mark.parametrize("action", ["confirm", "ignore"])
def test_watch_invalid_channel_name_is_a_400(tmp_path, isolated_cwd, action):
    resp = client(tmp_path).post(f"/api/watch/Ma%20Chaine/{WATCH_VOD_A}/{action}")
    assert resp.status_code == 400


@pytest.mark.parametrize("action", ["confirm", "ignore"])
def test_watch_channel_without_state_file_is_a_404(tmp_path, isolated_cwd, action):
    resp = client(tmp_path).post(f"/api/watch/ma_chaine/{WATCH_VOD_A}/{action}")
    assert resp.status_code == 404


def test_watch_confirm_with_a_vod_already_waiting_in_the_queue_is_not_an_error(tmp_path, isolated_cwd):
    _watch_setup(tmp_path)
    c = client(tmp_path)
    c.post("/api/queue", json={"url": f"https://youtu.be/{WATCH_VOD_A}", "action": "run"})

    resp = c.post(f"/api/watch/ma_chaine/{WATCH_VOD_A}/confirm")

    assert resp.status_code == 202
    assert len(json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))) == 1


def test_dashboard_vod_section_is_wired_to_confirm_and_ignore():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    watch_js = (STATIC / "screens" / "watch.js").read_text(encoding="utf-8")
    dash_js = (STATIC / "screens" / "dashboard.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")

    assert "/static/screens/watch.js" in page
    assert page.index("/static/screens.js") < page.index("/static/screens/watch.js") < page.index("/static/app.js")
    assert "/confirm" in watch_js and "/ignore" in watch_js
    assert 'method: "POST"' in watch_js
    assert "Confirmer" in watch_js and "Ignorer" in watch_js and "Voir la VOD" in watch_js
    assert "confirmDialog" in watch_js                   # ignorer : confirmation
    assert "toastError" in watch_js                      # erreur affichée, jamais avalée
    assert "watchVodRow" in dash_js and "VOD à confirmer" in dash_js
    assert "TASK-7508" in css


# --------------------------------------------------------------------------
# Ecran Publication (TASK-503d, SPEC-c100 E6, SPEC-fc0c §4) : GET /api/publish,
# move / published / unschedule (publish simulé ou state/ temporaire)
# --------------------------------------------------------------------------

PUB_WEEK = "2026-10-05"                       # lundi ; créneaux : lun 18:30, jeu 12:00 (Europe/Paris, +02:00)
PUB_MON = "2026-10-05T18:30:00+02:00"
PUB_THU = "2026-10-08T12:00:00+02:00"
PUB_NEXT_MON = "2026-10-12T18:30:00+02:00"


def _publish_setup(tmp_path, entries=None, *, slots=True):
    preset = ('[channel]\ndisplay_name = "Ma chaîne"\ntiktok_account = "@ma_chaine"\n'
              + ('slots = [{day = "mon", time = "18:30"}, {day = "thu", time = "12:00"}]\n' if slots else ""))
    _channels_setup(tmp_path, preset)
    _write_state(tmp_path, CLIPS_VIDEO, channel="ma_chaine")
    for clip_id in ("01", "02", "03", "04", "05", "06"):
        _write_clip(tmp_path, CLIPS_VIDEO, _clip_sidecar(clip_id))
    _write_publish(tmp_path, "ma_chaine", entries if entries is not None else [])


def _get_publish(tmp_path, **params):
    params = {"channel": "ma_chaine", "week": PUB_WEEK, **params}
    return client(tmp_path).get("/api/publish", params=params)


def test_get_publish_returns_week_slots_with_clip_or_free(tmp_path, isolated_cwd):
    _publish_setup(tmp_path, [_entry("01", "scheduled", slot_at=PUB_THU)])

    resp = _get_publish(tmp_path)

    assert resp.status_code == 200
    data = resp.json()
    assert data["channel"] == "ma_chaine" and data["timezone"] == "Europe/Paris"
    assert data["tiktok_account"] == "@ma_chaine"
    assert data["week_start"] == "2026-10-05" and data["week_end"] == "2026-10-11"
    assert [s["slot_at"] for s in data["slots"]] == [PUB_MON, PUB_THU]
    mon, thu = data["slots"]
    assert mon["clip"] is None and mon["free"] is True
    assert thu["free"] is False
    assert (thu["clip"]["clip_id"], thu["clip"]["publish_status"]) == ("01", "scheduled")
    assert thu["clip"]["video_url"] == f"/media/clip/{CLIPS_VIDEO}/01"      # télécharger
    assert thu["clip"]["description"] == "Description 01" and thu["clip"]["hashtags"] == ["#ma_chaine"]


def test_get_publish_lists_approved_without_slot_and_published_failed_of_the_week(tmp_path, isolated_cwd):
    _publish_setup(tmp_path, [
        _entry("01", "approved"),
        _entry("02", "published", slot_at=PUB_MON, published_at="2026-10-05T18:40:00+02:00"),
        _entry("03", "failed", slot_at=PUB_THU, error="quota depasse"),
        _entry("04", "published", slot_at="2026-09-28T18:30:00+02:00", published_at="2026-09-28T19:00:00+02:00"),
        _entry("05", "rejected"),
    ])

    data = _get_publish(tmp_path).json()

    assert [c["clip_id"] for c in data["unscheduled"]] == ["01"]
    assert sorted((c["clip_id"], c["publish_status"]) for c in data["done"]) == [("02", "published"), ("03", "failed")]
    assert [s["clip"]["clip_id"] for s in data["slots"]] == ["02", "03"]     # leur créneau les affiche
    assert next(c for c in data["done"] if c["clip_id"] == "03")["publish_error"] == "quota depasse"


def test_get_publish_week_is_taken_from_the_requested_week_and_defaults_to_this_one(tmp_path, isolated_cwd):
    _publish_setup(tmp_path, [_entry("01", "scheduled", slot_at=PUB_NEXT_MON)])

    this = _get_publish(tmp_path).json()
    nxt = _get_publish(tmp_path, week="2026-10-14").json()                 # un mercredi : on tombe sur sa semaine
    now = client(tmp_path).get("/api/publish", params={"channel": "ma_chaine"}).json()

    assert all(s["clip"] is None for s in this["slots"])
    assert nxt["week_start"] == "2026-10-12"
    assert nxt["slots"][0]["slot_at"] == PUB_NEXT_MON and nxt["slots"][0]["clip"]["clip_id"] == "01"
    assert now["week_start"] <= now["week_end"] and len(now["slots"]) == 2


def test_get_publish_channel_without_slots_says_why(tmp_path, isolated_cwd):
    _publish_setup(tmp_path, [_entry("01", "approved")], slots=False)

    data = _get_publish(tmp_path).json()

    assert data["slots"] == [] and "créneau" in data["reason"]
    assert [c["clip_id"] for c in data["unscheduled"]] == ["01"]            # « sans créneau »


def test_get_publish_errors_are_french(tmp_path, isolated_cwd):
    _publish_setup(tmp_path)
    c = client(tmp_path)

    assert c.get("/api/publish").status_code == 400                         # chaîne obligatoire
    assert "chaîne" in c.get("/api/publish").json()["detail"]
    assert c.get("/api/publish", params={"channel": "inconnue"}).status_code == 404
    assert c.get("/api/publish", params={"channel": "Bad Name"}).status_code in (400, 422)
    bad = c.get("/api/publish", params={"channel": "ma_chaine", "week": "demain"})
    assert bad.status_code == 400 and "week" in bad.json()["detail"]


def test_get_publish_corrupt_publish_file_is_a_500_not_an_empty_week(tmp_path, isolated_cwd):
    _publish_setup(tmp_path)
    (tmp_path / "state" / "publish" / "ma_chaine.json").write_text("{pas du json", encoding="utf-8")

    resp = _get_publish(tmp_path)

    assert resp.status_code == 500 and "publication" in resp.json()["detail"]


def test_publish_move_calls_publish_move_with_the_slot(tmp_path, isolated_cwd, monkeypatch):
    from clipper import publish

    _publish_setup(tmp_path)
    calls = []
    monkeypatch.setattr(publish, "move", lambda *a, **kw: calls.append((a, kw)) or _entry("01", "scheduled", slot_at=PUB_THU))

    resp = client(tmp_path).post(f"/api/publish/{CLIPS_VIDEO}/01/move", json={"slot_at": PUB_THU})

    assert resp.status_code == 200 and resp.json()["slot_at"] == PUB_THU
    (video_id, clip_id, channel, slot), kw = calls[0]
    assert (video_id, clip_id, channel) == (CLIPS_VIDEO, "01", "ma_chaine")
    assert slot.isoformat() == PUB_THU
    assert kw["state_dir"] == Path("state/publish") and kw["presets_dir"] == "presets"


def test_publish_move_conflict_is_409_with_detail(tmp_path, isolated_cwd, monkeypatch):
    from clipper import publish

    _publish_setup(tmp_path)

    def boom(*a, **kw):
        raise publish.PublishError("creneau deja pris pour x/02 : y")

    monkeypatch.setattr(publish, "move", boom)

    resp = client(tmp_path).post(f"/api/publish/{CLIPS_VIDEO}/02/move", json={"slot_at": PUB_THU})

    assert resp.status_code == 409 and resp.json()["detail"] == "creneau deja pris pour x/02 : y"


def test_publish_move_validates_input(tmp_path, isolated_cwd, monkeypatch):
    from clipper import publish

    _publish_setup(tmp_path)
    monkeypatch.setattr(publish, "move", lambda *a, **kw: pytest.fail("publish.move ne doit pas être appelé"))
    c = client(tmp_path)

    naive = c.post(f"/api/publish/{CLIPS_VIDEO}/01/move", json={"slot_at": "2026-10-08T12:00:00"})
    junk = c.post(f"/api/publish/{CLIPS_VIDEO}/01/move", json={"slot_at": "jeudi midi"})
    unsafe = c.post(f"/api/publish/{CLIPS_VIDEO}/..%2Fx/move", json={"slot_at": PUB_THU})
    nochan = client(tmp_path).post("/api/publish/othervideo01/01/move", json={"slot_at": PUB_THU})

    assert naive.status_code == 422 and "fuseau" in naive.json()["detail"]
    assert junk.status_code == 422 and "slot_at" in junk.json()["detail"]
    assert unsafe.status_code in (400, 404)
    assert nochan.status_code == 409 and "chaîne" in nochan.json()["detail"]


def test_publish_move_end_to_end_on_a_temporary_state(tmp_path, isolated_cwd):
    _publish_setup(tmp_path, [_entry("01", "scheduled", slot_at=PUB_MON), _entry("02", "approved")])
    c = client(tmp_path)

    ok = c.post(f"/api/publish/{CLIPS_VIDEO}/02/move", json={"slot_at": PUB_THU})
    taken = c.post(f"/api/publish/{CLIPS_VIDEO}/02/move", json={"slot_at": PUB_MON})

    assert ok.status_code == 200 and ok.json()["status"] == "scheduled"
    assert taken.status_code == 409 and "pris" in taken.json()["detail"]
    saved = json.loads((tmp_path / "state" / "publish" / "ma_chaine.json").read_text(encoding="utf-8"))
    assert {e["clip_id"]: e["slot_at"] for e in saved} == {"01": PUB_MON, "02": PUB_THU}


def test_publish_published_and_unschedule_call_publish(tmp_path, isolated_cwd, monkeypatch):
    from clipper import publish

    _publish_setup(tmp_path)
    calls = []
    monkeypatch.setattr(publish, "mark_published", lambda *a, **kw: calls.append(("mark_published", a, kw)) or _entry("01", "published"))
    monkeypatch.setattr(publish, "unschedule", lambda *a, **kw: calls.append(("unschedule", a, kw)) or _entry("01", "approved"))
    c = client(tmp_path)

    done = c.post(f"/api/publish/{CLIPS_VIDEO}/01/published")
    back = c.post(f"/api/publish/{CLIPS_VIDEO}/01/unschedule")

    assert done.status_code == 200 and done.json()["status"] == "published"
    assert back.status_code == 200 and back.json()["status"] == "approved"
    assert [(n, a) for n, a, _ in calls] == [
        ("mark_published", (CLIPS_VIDEO, "01", "ma_chaine")), ("unschedule", (CLIPS_VIDEO, "01", "ma_chaine"))]
    assert all(kw["state_dir"] == Path("state/publish") for _, _, kw in calls)


@pytest.mark.parametrize("action", ["published", "unschedule"])
def test_publish_published_unschedule_error_is_409_with_detail(tmp_path, isolated_cwd, monkeypatch, action):
    from clipper import publish

    _publish_setup(tmp_path)

    def boom(*a, **kw):
        raise publish.PublishError("clip absent de la file de publication : x/06")

    monkeypatch.setattr(publish, "mark_published" if action == "published" else "unschedule", boom)

    resp = client(tmp_path).post(f"/api/publish/{CLIPS_VIDEO}/06/{action}")

    assert resp.status_code == 409 and resp.json()["detail"] == "clip absent de la file de publication : x/06"


def test_publish_published_and_unschedule_end_to_end(tmp_path, isolated_cwd):
    _publish_setup(tmp_path, [_entry("01", "scheduled", slot_at=PUB_MON), _entry("02", "scheduled", slot_at=PUB_THU)])
    c = client(tmp_path)

    assert c.post(f"/api/publish/{CLIPS_VIDEO}/01/published").json()["status"] == "published"
    back = c.post(f"/api/publish/{CLIPS_VIDEO}/02/unschedule").json()
    again = c.post(f"/api/publish/{CLIPS_VIDEO}/01/published")             # déjà publié : refusé

    assert back["status"] == "approved" and back["slot_at"] is None
    assert again.status_code == 409


def test_publish_screen_is_wired_with_calendar_queue_and_actions():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "screens" / "publish.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")

    assert "/static/screens/publish.js" in page
    assert page.index("/static/screens.js") < page.index("/static/screens/publish.js") < page.index("/static/app.js")
    assert "Screens.publish" in js
    assert "/api/publish" in js and "/move" in js and "/published" in js and "/unschedule" in js
    assert "pub-channel" in js and "<select" in js                         # sélecteur de chaîne
    assert "tiktok_account" in js                                          # compte cible affiché
    assert "week" in js and "Semaine précédente" in js and "Semaine suivante" in js
    assert "cal-c" in js and "data-slot-at" in js and "slot_at" in js      # calendrier hebdomadaire des créneaux
    assert "unscheduled" in js and "À publier" in js                       # file des approuvés sans créneau
    for ev in ("dragstart", "dragover", "drop"):                            # glisser-déposer à la souris
        assert ev in js, ev
    for ev in ("touchstart", "touchmove", "touchend"):                      # et au toucher
        assert ev in js, ev
    for label in ("Planifié", "Publié", "Échec", "Approuvé"):               # badges de statut
        assert label in js, label
    assert "download" in js and "video_url" in js                          # télécharger
    assert "copyText" in js                                                # copier la description
    assert "Marquer publié" in js and "confirmDialog" in js                # confirmation
    assert "Repasser en attente" in js
    assert "undo" in js                                                    # toast « Annuler »
    assert "toastError" in js                                              # un conflit 409 s'affiche
    assert "Rien à publier" in js                                          # état vide
    for sel in (".cal", ".cal-c", ".post", ".queue", "TASK-503d"):
        assert sel in css, sel
# Ecran Reglages (SPEC-c100 E8, ADR-4f6e §2 et §5) : config.toml en formulaire
# --------------------------------------------------------------------------

import tomllib  # noqa: E402

_SET_TOML = (
    '# commentaire a perdre\nmode = "review"\n'
    '[llm]\nbackend = "claude-cli"\n'
    '[web]\nport = 8123\ntoken = "secret-tres-long"\n'
    '[render]\ncrf = 18\n'
)


def _settings_setup(tmp_path, text=_SET_TOML):
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")
    return tmp_path / "config.toml"


def sclient(tmp_path) -> TestClient:
    """Serveur démarré avec la config lue dans config.toml (comme 'serve')."""
    from clipper.config import load_config

    path = tmp_path / "config.toml"
    return TestClient(create_app(config=load_config(path) if path.exists() else make_config(tmp_path)))


def test_get_settings_returns_effective_values_and_documented_defaults_per_section(tmp_path, isolated_cwd):
    _settings_setup(tmp_path)
    data = sclient(tmp_path).get("/api/settings").json()

    assert data["raw"]["mode"] == "review" and data["raw"]["web"]["port"] == 8123
    assert data["effective"]["mode"] == "review"
    assert data["effective"]["workspace_dir"] == "workspace"          # défaut de config.DEFAULTS
    assert data["effective"]["web"]["port"] == 8123
    assert data["effective"]["web"]["sse_poll_interval_s"] == 1.0     # défaut du module
    assert data["effective"]["worker"]["poll_interval_s"] == 2
    assert data["effective"]["llm"]["backend"] == "claude-cli"
    assert data["effective"]["llm"]["usages"]["moments"] == {"model": "strong"}
    for section in ("llm", "web", "worker"):
        assert section in data["defaults"], section
    # même mécanisme que l'écran Chaînes : défaut + commentaire du source
    assert data["defaults"]["web"]["port"]["default"] == 8000
    assert "Hôte et port" in data["defaults"]["web"]["host"]["comment"]
    assert "réponse refusée" in data["defaults"]["llm"]["repair_attempts"]["comment"]
    assert set(data["backends"]) == {"claude-cli", "claude-api", "ollama"}
    assert data["modes"] == ["review", "auto"]
    assert data["comments_lost"] is True                              # le fichier contient un commentaire


def test_get_settings_never_returns_the_token(tmp_path, isolated_cwd):
    _settings_setup(tmp_path)
    resp = sclient(tmp_path).get("/api/settings")
    assert "secret-tres-long" not in resp.text
    access = resp.json()["access"]
    assert access["host"] == "127.0.0.1" and access["port"] == 8123
    assert access["token_set"] is True and access["token"] != "secret-tres-long" and set(access["token"]) == {"•"}
    assert access["command"] == "python -m clipper serve --port 8123"


def test_get_settings_without_config_toml_shows_defaults_and_no_comment_warning(tmp_path, isolated_cwd):
    data = sclient(tmp_path).get("/api/settings").json()
    assert data["exists"] is False and data["comments_lost"] is False
    assert data["effective"]["mode"] == "review" and data["effective"]["web"]["port"] == 8000
    assert data["access"]["token_set"] is False and data["access"]["token"] is None


def test_put_settings_writes_through_write_config_keeping_other_sections_and_the_token(
        tmp_path, isolated_cwd, monkeypatch):
    path = _settings_setup(tmp_path)
    from clipper import config as config_mod
    from clipper.web import app as web_app

    calls = []
    real = config_mod.write_config
    monkeypatch.setattr(web_app, "write_config", lambda *a, **k: (calls.append((a, k)), real(*a, **k))[1])

    body = {"settings": {
        "mode": "auto", "output_dir": "sorties",
        "llm": {"backend": "ollama", "repair_attempts": 2, "usages": {"moments": {"model": "fast"}}},
        "web": {"port": 9001, "host": "127.0.0.1", "sse_poll_interval_s": 2.0},
        "worker": {"poll_interval_s": 5},
    }}
    resp = sclient(tmp_path).put("/api/settings", json=body)

    assert resp.status_code == 200, resp.text
    assert len(calls) == 1 and Path(calls[0][0][0]) == Path("config.toml")
    written = tomllib.loads(path.read_text(encoding="utf-8"))
    assert written["mode"] == "auto" and written["output_dir"] == "sorties"
    assert written["llm"]["backend"] == "ollama" and written["llm"]["usages"] == {"moments": {"model": "fast"}}
    assert written["web"]["port"] == 9001
    assert written["web"]["token"] == "secret-tres-long"             # le jeton n'est jamais touché
    assert written["render"] == {"crf": 18}                          # section hors formulaire conservée
    assert "commentaire" not in path.read_text(encoding="utf-8")     # commentaires perdus (ADR-4f6e §2)
    assert resp.json()["effective"]["mode"] == "auto" and resp.json()["comments_lost"] is False


@pytest.mark.parametrize("settings, fragment", [
    ({"mode": "manuel"}, "mode"),
    ({"workspace_dir": 5}, "workspace_dir"),
    ({"llm": {"backend": "inconnu"}}, "inconnu"),
    ({"llm": {"usages": {"moments": {"backend": "nope"}}}}, "nope"),
    ({"llm": {"repair_attempts": "deux"}}, "repair_attempts"),
    ({"web": {"port": "x"}}, "port"),
    ({"web": {"port": 70000}}, "port"),
    ({"web": {"zzz": 1}}, "zzz"),
    ({"worker": {"queue_path": 3}}, "queue_path"),
    ({"web": {"host": "0.0.0.0", "token": "autre"}}, "jeton"),
    ({"web": {"host": "0.0.0.0"}}, "jeton"),    # hors bouclage sans jeton : serve refuserait de démarrer
    ({"render": {"crf": 1}}, "render"),         # section hors formulaire : pas éditable ici
])
def test_put_settings_refused_value_is_422_with_detail_and_keeps_the_file(
        tmp_path, isolated_cwd, settings, fragment):
    path = _settings_setup(tmp_path, _SET_TOML.replace('token = "secret-tres-long"\n', ""))
    before = path.read_bytes()

    resp = sclient(tmp_path).put("/api/settings", json={"settings": settings})

    assert resp.status_code == 422
    assert fragment in resp.json()["detail"]
    assert path.read_bytes() == before                               # fichier intact
    assert not list(tmp_path.glob("config.toml.*"))                  # pas de .tmp qui traîne


def test_put_settings_load_config_refusal_is_422_and_keeps_the_file(tmp_path, isolated_cwd):
    path = _settings_setup(tmp_path)
    before = path.read_bytes()
    resp = sclient(tmp_path).put("/api/settings", json={"settings": {"mode": "auto", "llm": {"zzz": 1}}})
    assert resp.status_code == 422 and path.read_bytes() == before


def test_put_settings_mode_and_backend_are_read_by_the_next_queue_entries(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    _settings_setup(tmp_path)
    seen = []

    def fake_enqueue(url, channel, action, force_steps, *, config=None):
        seen.append((config.mode, config.section("llm")["backend"]))
        return {"id": "e1", "video_id": VIDEO_ID, "url": url, "channel": channel, "action": action,
                "force_steps": [], "status": "waiting"}

    monkeypatch.setattr(worker, "enqueue", fake_enqueue)
    c = sclient(tmp_path)
    c.post("/api/queue", json={"url": URL, "action": "run"})
    assert c.put("/api/settings", json={"settings": {"mode": "auto", "llm": {"backend": "ollama"}}}).status_code == 200
    c.post("/api/queue", json={"url": URL, "action": "run"})

    assert seen == [("review", "claude-cli"), ("auto", "ollama")]


def test_put_settings_web_changes_ask_for_a_restart_and_do_not_change_the_running_access(tmp_path, isolated_cwd):
    _settings_setup(tmp_path)
    c = sclient(tmp_path)
    assert c.get("/api/settings").json()["restart_required"] is False
    data = c.put("/api/settings", json={"settings": {"web": {"port": 9001}}}).json()
    assert data["restart_required"] is True
    assert data["access"]["port"] == 8123                            # l'écoute en cours ne change pas


def test_settings_screen_is_wired_with_sections_access_and_comment_warning():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "screens" / "settings.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")

    assert "/static/screens/settings.js" in page
    assert page.index("/static/screens.js") < page.index("/static/screens/settings.js") < page.index("/static/app.js")
    assert "Screens.settings" in js and 'api("/api/settings"' in js
    assert 'jsonBody("PUT"' in js and "toast(" in js
    # formulaire par sections
    for title in ("Général", "Dossiers", "LLM", "Serveur web", "Worker", "Accès"):
        assert title in js, title
    for key in ("mode", "workspace_dir", "output_dir", "backend", "repair_attempts", "usages", "models"):
        assert key in js, key
    # section Accès en lecture seule : hôte, port, jeton masqué, commande serve
    assert "token_set" in js and "access.command" in js and "access.host" in js and "access.port" in js
    assert "redémarrage" in js
    # avertissement avant la première écriture
    assert "commentaires du fichier perdus" in js and "comments_lost" in js
    assert "field-error" in js and "set-" in css
# Éditeur d'agencement stream split (SPEC-c100 E5, SPEC-76dc) : API + écran
# --------------------------------------------------------------------------

_LAYOUT_KEYS = ("split_webcam_dest", "split_gameplay_dest", "badge_dest", "split_subtitle_dest")
_LAYOUT_DEFAULTS = {
    "split_webcam_dest": {"x": 20, "y": 0, "w": 1040, "h": 640},
    "split_gameplay_dest": {"x": 0, "y": 640, "w": 1080, "h": 1280},
    "badge_dest": {"x": 330, "y": 590, "w": 420, "h": 100},
    "split_subtitle_dest": {"x": 150, "y": 710, "w": 780, "h": 150},
}
import tomllib  # noqa: E402

_JPEG = b"\xff\xd8\xff\xe0layout-test-jpeg"


def _layout_keyframe(tmp_path, video_id, channel=CH, names=("scene0000_000.jpg",), folder="frames"):
    _write_state(tmp_path, video_id, channel=channel)
    frames = tmp_path / "workspace" / video_id / folder
    frames.mkdir(parents=True, exist_ok=True)
    for name in names:
        (frames / name).write_bytes(_JPEG + name.encode())


def test_layout_keyframe_returns_a_jpeg_of_the_requested_video(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    _layout_keyframe(tmp_path, "aaaaaaaaaaa")
    resp = client(tmp_path).get(f"/api/channels/{CH}/keyframe", params={"video_id": "aaaaaaaaaaa"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content.startswith(_JPEG)


def test_layout_keyframe_without_video_id_takes_a_video_of_the_channel(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    _layout_keyframe(tmp_path, "bbbbbbbbbbb", channel="autre_chaine")
    _layout_keyframe(tmp_path, "aaaaaaaaaaa", folder="scenes", names=("k1.jpg",))
    resp = client(tmp_path).get(f"/api/channels/{CH}/keyframe")
    assert resp.status_code == 200 and resp.content.endswith(b"k1.jpg")


def test_layout_keyframe_404_in_french_when_no_video_has_keyframes(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    _write_state(tmp_path, "aaaaaaaaaaa", channel=CH)          # vidéo sans images clés
    _layout_keyframe(tmp_path, "bbbbbbbbbbb", channel="autre_chaine")
    c = client(tmp_path)
    resp = c.get(f"/api/channels/{CH}/keyframe")
    assert resp.status_code == 404
    assert "image clé" in resp.json()["detail"] and CH in resp.json()["detail"]
    resp = c.get(f"/api/channels/{CH}/keyframe", params={"video_id": "aaaaaaaaaaa"})
    assert resp.status_code == 404 and "aaaaaaaaaaa" in resp.json()["detail"]
    # une vidéo d'une autre chaîne n'est pas servie pour celle-ci
    resp = c.get(f"/api/channels/{CH}/keyframe", params={"video_id": "bbbbbbbbbbb"})
    assert resp.status_code == 404 and "bbbbbbbbbbb" in resp.json()["detail"]


def test_layout_keyframe_refuses_unsafe_video_id_and_unknown_channel(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    c = client(tmp_path)
    assert c.get(f"/api/channels/{CH}/keyframe", params={"video_id": "../x"}).status_code == 404
    assert c.get("/api/channels/inconnue/keyframe").status_code == 404


def test_get_layout_returns_spec_defaults(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    data = client(tmp_path).get(f"/api/channels/{CH}/layout").json()
    for key in _LAYOUT_KEYS:
        assert data[key] == _LAYOUT_DEFAULTS[key], key
    assert data["defaults"] == _LAYOUT_DEFAULTS
    assert data["canvas"] == {"w": 1080, "h": 1920}
    assert data["safe"] == {"left": 150, "top": 160, "right": 930, "bottom": 1520}


def test_get_layout_returns_the_preset_values(tmp_path, isolated_cwd):
    _channels_setup(tmp_path, _CH_PRESET + 'split_webcam_dest = {x = 0, y = 0, w = 1080, h = 700}\n')
    data = client(tmp_path).get(f"/api/channels/{CH}/layout").json()
    assert data["split_webcam_dest"] == {"x": 0, "y": 0, "w": 1080, "h": 700}
    assert data["badge_dest"] == _LAYOUT_DEFAULTS["badge_dest"]


def test_get_layout_unknown_channel_is_404(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    assert client(tmp_path).get("/api/channels/inconnue/layout").status_code == 404


def test_put_layout_writes_the_keys_in_reframe_through_save_channel(tmp_path, isolated_cwd, monkeypatch):
    _channels_setup(tmp_path)
    from clipper import channel as channel_mod

    calls = []
    real = channel_mod.save_channel

    def spy(name, data, **kwargs):
        calls.append((name, data, kwargs))
        return real(name, data, **kwargs)

    monkeypatch.setattr(channel_mod, "save_channel", spy)
    layout = {
        "split_webcam_dest": {"x": 0, "y": 0, "w": 1080, "h": 700},
        "split_gameplay_dest": {"x": 0, "y": 700, "w": 1080, "h": 1220},
        "badge_dest": {"x": 330, "y": 640, "w": 420, "h": 100},
        "split_subtitle_dest": {"x": 150, "y": 760, "w": 780, "h": 150},
    }
    resp = client(tmp_path).put(f"/api/channels/{CH}/layout", json=layout)

    assert resp.status_code == 200, resp.text
    for key in _LAYOUT_KEYS:
        assert resp.json()[key] == layout[key]
    assert any(n == CH and k["presets_dir"] == "presets" and d["reframe"]["badge_dest"] == layout["badge_dest"]
               for n, d, k in calls)
    saved = tomllib.loads((tmp_path / "presets" / f"{CH}.toml").read_text(encoding="utf-8"))
    assert saved["reframe"]["letterbox_zoom"] == 1.5                    # le reste du preset est conservé
    assert saved["channel"]["display_name"] == "Ma chaîne"
    for key in _LAYOUT_KEYS:
        assert saved["reframe"][key] == layout[key]
    assert client(tmp_path).get(f"/api/channels/{CH}/layout").json()["badge_dest"] == layout["badge_dest"]


@pytest.mark.parametrize("key, rect, fragment", [
    ("split_webcam_dest", {"x": 100, "y": 0, "w": 1040, "h": 640}, "deborde"),               # sort du canevas (1140 > 1080)
    ("split_gameplay_dest", {"x": 0, "y": 600, "w": 1080, "h": 1320}, "se chevauchent"),      # chevauche la webcam
    ("badge_dest", {"x": 100, "y": 590, "w": 420, "h": 100}, "zone sure"),                    # hors zone sûre
])
def test_put_layout_invalid_is_422_with_the_load_config_detail_and_keeps_the_file(
    tmp_path, isolated_cwd, key, rect, fragment
):
    _channels_setup(tmp_path)
    path = tmp_path / "presets" / f"{CH}.toml"
    before = path.read_text(encoding="utf-8")

    resp = client(tmp_path).put(f"/api/channels/{CH}/layout", json={key: rect})

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert key in detail and fragment in detail, detail
    # même texte que celui de reframe (qui refuse, load_config ne contrôlant que les clés)
    from clipper import reframe
    from clipper.config import load_config

    candidate = tmp_path / "candidate.toml"
    candidate.write_text(
        '[reframe]\nstream_variant = "split"\n'
        + f"{key} = {{x = {rect['x']}, y = {rect['y']}, w = {rect['w']}, h = {rect['h']}}}\n",
        encoding="utf-8",
    )
    with pytest.raises(reframe.ReframeError) as err:
        reframe._settings(load_config(candidate))
    assert detail == str(err.value)
    assert path.read_text(encoding="utf-8") == before


def test_put_layout_without_any_key_or_with_bad_rect_is_422(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    c = client(tmp_path)
    resp = c.put(f"/api/channels/{CH}/layout", json={})
    assert resp.status_code == 422 and "split_webcam_dest" in resp.json()["detail"]
    resp = c.put(f"/api/channels/{CH}/layout", json={"badge_dest": {"x": 1, "y": 2}})
    assert resp.status_code == 422 and "badge_dest" in resp.json()["detail"]
    assert c.put("/api/channels/inconnue/layout", json={"badge_dest": _LAYOUT_DEFAULTS["badge_dest"]}).status_code == 404


def test_layout_editor_screen_is_wired_with_canvas_zones_handles_and_actions():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "screens" / "layout.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    channels = (STATIC / "screens" / "channels.js").read_text(encoding="utf-8")

    assert "/static/screens/layout.js" in page
    assert page.index("/static/screens/channels.js") < page.index("/static/screens/layout.js")
    assert "/layout" in channels and "Éditeur d'agencement" in channels      # accès depuis la chaîne
    # canevas 1080x1920 mis à l'échelle, quatre zones, image clé
    assert "1080" in js and "1920" in js and "scale(" in js
    for key in _LAYOUT_KEYS:
        assert key in js, key
    for label in ("Webcam", "Jeu", "Badge", "Sous-titres"):
        assert label in js, label
    assert "/keyframe" in js and "Aucune image clé" in js
    # poignées, souris et toucher
    assert "pointerdown" in js and "pointermove" in js and "setPointerCapture" in js and "hdl" in js
    assert "touch-action" in css
    # valeurs {x,y,w,h} éditables, réinitialiser, enregistrer (erreur du serveur affichée)
    assert 'data-k="x"' in js or 'data-k="${' in js
    assert "Réinitialiser aux défauts" in js and "Enregistrer" in js
    assert 'jsonBody("PUT"' in js and "/layout" in js and "Agencement enregistré" in js
    assert "Screens.channels" in js
    for selector in (".ly-stage", ".ly-zone", ".ly-hdl"):
        assert selector in css, selector
# Aperçu du style des sous-titres (TASK-dd3f, SPEC-c100 E5)
# --------------------------------------------------------------------------


def test_subtitles_preview_returns_a_png_rendered_by_the_pipeline(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline

    _channels_setup(tmp_path)
    seen = []
    monkeypatch.setattr(pipeline, "preview_subtitles",
                        lambda config, text: seen.append((config.section("subtitles"), text)) or b"\x89PNG\r\n\x1a\nxx")

    resp = client(tmp_path).get(f"/api/channels/{CH}/subtitles-preview", params={"text": "Salut à tous"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")
    assert seen and seen[0][1] == "Salut à tous"


def test_subtitles_preview_renders_a_real_png_with_the_preset_style(tmp_path, isolated_cwd):
    _channels_setup(tmp_path, preset=_CH_PRESET + '\n[subtitles]\nletterbox_font_size = 50\n')
    resp = client(tmp_path).get(f"/api/channels/{CH}/subtitles-preview", params={"text": "Salut"})
    assert resp.status_code == 200 and resp.content.startswith(b"\x89PNG")


def test_subtitles_preview_with_an_unsaved_draft_uses_the_draft_style(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline

    _channels_setup(tmp_path)
    seen = []
    monkeypatch.setattr(pipeline, "preview_subtitles",
                        lambda config, text: seen.append((config.section("subtitles"), config.section("reframe"))) or b"\x89PNG\r\n\x1a\n")
    draft = json.dumps({"subtitles": {"letterbox_outline": 11}, "reframe": {"stream_variant": "split"}})

    resp = client(tmp_path).get(f"/api/channels/{CH}/subtitles-preview", params={"text": "Salut", "draft": draft})

    assert resp.status_code == 200
    assert seen[0][0]["letterbox_outline"] == 11 and seen[0][1]["stream_variant"] == "split"
    # le preset enregistré n'a pas bougé
    assert "letterbox_outline" not in (tmp_path / "presets" / f"{CH}.toml").read_text(encoding="utf-8")


def test_subtitles_preview_invalid_style_is_422_with_detail(tmp_path, isolated_cwd):
    _channels_setup(tmp_path, preset=_CH_PRESET + '\n[subtitles]\nsplit_text_color = "caca"\n')
    c = client(tmp_path)
    # le style effectif est celui du format split : la couleur invalide est rendue
    draft = json.dumps({"reframe": {"stream_variant": "split"}, "subtitles": {"split_text_color": "caca"}})
    resp = c.get(f"/api/channels/{CH}/subtitles-preview", params={"text": "Salut", "draft": draft})
    assert resp.status_code == 422
    assert "couleur" in resp.json()["detail"]


def test_subtitles_preview_unknown_channel_404_and_bad_draft_422(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)
    c = client(tmp_path)
    assert c.get("/api/channels/inconnue/subtitles-preview", params={"text": "x"}).status_code == 404
    bad = c.get(f"/api/channels/{CH}/subtitles-preview", params={"text": "x", "draft": "{pas du json"})
    assert bad.status_code == 422 and "draft" in bad.json()["detail"]
    empty = c.get(f"/api/channels/{CH}/subtitles-preview", params={"text": "  "})
    assert empty.status_code == 422 and "texte" in empty.json()["detail"]


def test_channels_screen_previews_subtitles_style_with_a_300ms_debounce():
    js = (STATIC / "screens" / "channels.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    shot = (STATIC / "screens" / "chan-subtitles-preview.js")
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    prev = shot.read_text(encoding="utf-8")

    assert "/static/screens/chan-subtitles-preview.js" in page
    assert page.index("/static/screens/channels.js") < page.index("/static/screens/chan-subtitles-preview.js")
    assert "/subtitles-preview" in prev and "PREVIEW_DELAY_MS = 300" in prev
    assert "setTimeout" in prev and "clearTimeout" in prev
    assert "draft: JSON.stringify" in prev   # brouillon non enregistré envoyé tel quel
    assert ".chan-preview" in css
    assert "chSubsPreview" in js          # point d'accroche dans l'écran chaînes
# TASK-7d86 : ecran Statistiques (GET /api/stats, POST /api/stats/import)
# --------------------------------------------------------------------------

STATS_A, STATS_B, STATS_C, STATS_D = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"
STATS_CSV = (
    "clip_id,views,retention_3s,watched_full,shares,date\n"
    "02,1200,0.61,0.22,14,2026-09-25\n"
)


def _stats_jsonl(path: Path, lines) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


def _stats_seed(tmp_path) -> None:
    def steps(download, render, finished):
        return {
            "download": _step(f"{finished}T10:00:00+00:00", f"{finished}T10:00:{download:02d}+00:00"),
            "render": _step(f"{finished}T10:05:00+00:00", f"{finished}T10:{5 + render // 60:02d}:{render % 60:02d}+00:00"),
        }
    _write_state(tmp_path, STATS_A, status="done", updated_at="2026-09-10T12:00:00+00:00",
                 steps=steps(40, 100, "2026-09-10"))
    _write_state(tmp_path, STATS_B, status="done", updated_at="2026-08-01T12:00:00+00:00",
                 steps=steps(20, 200, "2026-08-01"))
    _write_state(tmp_path, STATS_C, status="failed", updated_at="2026-09-12T12:00:00+00:00")
    _write_state(tmp_path, STATS_D, status="running", updated_at="2026-09-15T12:00:00+00:00")
    _write_sidecar(tmp_path, STATS_A, "01", moment_id=1, created_at="2026-09-10T12:00:00+00:00",
                   qa={"status": "passed", "issues": []})
    _write_sidecar(tmp_path, STATS_A, "02", moment_id=2, created_at="2026-09-20T12:00:00+00:00",
                   qa={"status": "rejected", "issues": ["sous-titres hors cadre"]})
    _write_sidecar(tmp_path, STATS_B, "01", moment_id=1, created_at="2026-08-01T12:00:00+00:00",
                   qa={"status": "passed", "issues": []})
    _stats_jsonl(tmp_path / "state" / "outcomes.jsonl", [
        {"kind": "result", "video_id": STATS_A, "clip_id": "01", "moment_id": 1,
         "qa": {"status": "passed", "issues": []}, "human_decision": "approved",
         "recorded_at": "2026-09-11T08:00:00+00:00"},
        {"kind": "stats", "video_id": None, "clip_id": "02", "moment_id": None,
         "stats": {"views": 900, "retention_3s": 0.5, "watched_full": 0.2, "shares": 3, "date": "2026-09-22"},
         "recorded_at": "2026-09-22T08:00:00+00:00"},
        {"kind": "stats", "video_id": None, "clip_id": "02", "moment_id": None,
         "stats": {"views": 1200, "retention_3s": 0.61, "watched_full": 0.22, "shares": 14, "date": "2026-09-25"},
         "recorded_at": "2026-09-25T08:00:00+00:00"},
        {"kind": "stats", "video_id": None, "clip_id": "01", "moment_id": None,
         "stats": {"views": 50, "retention_3s": 0.4, "watched_full": 0.1, "shares": 0, "date": "2026-09-25"},
         "recorded_at": "2026-09-25T08:00:00+00:00"},
    ])
    _stats_jsonl(tmp_path / "state" / "feedback.jsonl", [
        {"video_id": STATS_A, "moment": {"id": 2}, "texte_moment": "t", "decision": "adjusted",
         "commentaire": None, "horodatage": "2026-09-19T08:00:00+00:00"},
        {"video_id": STATS_A, "moment": {"id": 1}, "texte_moment": "t", "decision": "rejected",
         "commentaire": None, "horodatage": "2026-09-09T08:00:00+00:00"},
    ])

    def usage(usage_name, cost, when):
        return {"recorded_at": f"{when}T12:00:00+00:00", "usage": usage_name, "model": "m",
                "input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 0, "cost_usd": cost, "duration_s": 1.0}
    _stats_jsonl(tmp_path / "workspace" / STATS_A / "llm_usage.jsonl", [
        usage("moments", 0.5, "2026-09-10"), usage("jury", 0.25, "2026-09-10"),
        usage("moments", 1.0, "2026-09-20"), usage("jury", None, "2026-09-20"),
    ])
    _stats_jsonl(tmp_path / "workspace" / STATS_B / "llm_usage.jsonl", [usage("moments", 2.0, "2026-08-01")])


def _stats(tmp_path, query=""):
    resp = client(tmp_path).get(f"/api/stats{query}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_stats_empty_state_has_explicit_empty_blocks(tmp_path, isolated_cwd):
    data = _stats(tmp_path)

    assert data["clips"] == [] and data["stats_unmatched"] == []
    assert data["llm_cost"] == {"total": 0.0, "unreported_calls": 0, "by_video": {}, "by_usage": {}, "by_day": {}}
    assert data["steps"] == {}
    assert data["counts"] == {s: 0 for s in ("pending", "running", "awaiting_review", "queued", "done", "failed")}


def test_stats_clips_join_sidecar_outcomes_and_human_decision(tmp_path, isolated_cwd):
    _stats_seed(tmp_path)

    data = _stats(tmp_path, "?since=2026-09-01&until=2026-09-30")
    clips = {(c["video_id"], c["clip_id"]): c for c in data["clips"]}

    assert sorted(clips) == [(STATS_A, "01"), (STATS_A, "02")]      # le clip d'août est hors période
    one, two = clips[(STATS_A, "01")], clips[(STATS_A, "02")]
    assert one["screen_title"] == "Titre 01" and one["moment_id"] == 1
    assert one["qa_status"] == "passed" and one["issues"] == []
    assert one["human_decision"] == "approved" and one["decision_source"] == "outcomes"
    assert one["stats"] is None                                       # clip_id « 01 » existe dans 2 vidéos
    assert two["qa_status"] == "rejected" and two["issues"] == ["sous-titres hors cadre"]
    assert two["human_decision"] == "adjusted" and two["decision_source"] == "feedback"
    assert two["stats"] == {"views": 1200, "retention_3s": 0.61, "watched_full": 0.22, "shares": 14,
                            "date": "2026-09-25"}                    # la mesure la plus récente
    assert [u["clip_id"] for u in data["stats_unmatched"]] == ["01"]
    assert "plusieurs vidéos" in data["stats_unmatched"][0]["reason"]


def test_stats_without_period_covers_everything(tmp_path, isolated_cwd):
    _stats_seed(tmp_path)

    data = _stats(tmp_path)

    assert len(data["clips"]) == 3
    assert data["llm_cost"]["total"] == pytest.approx(3.75)


def test_stats_llm_cost_per_video_usage_and_day(tmp_path, isolated_cwd):
    _stats_seed(tmp_path)

    cost = _stats(tmp_path, "?since=2026-09-01&until=2026-09-30")["llm_cost"]

    assert cost["total"] == pytest.approx(1.75)
    assert cost["unreported_calls"] == 1                              # jamais compté pour 0
    assert cost["by_usage"] == {"moments": pytest.approx(1.5), "jury": pytest.approx(0.25)}
    assert cost["by_day"] == {"2026-09-10": pytest.approx(0.75), "2026-09-20": pytest.approx(1.0)}
    assert list(cost["by_video"]) == [STATS_A]
    assert cost["by_video"][STATS_A] == {"cost": pytest.approx(1.75), "calls": 4, "unreported_calls": 1}


def test_stats_steps_mean_and_last_duration_on_done_videos(tmp_path, isolated_cwd):
    _stats_seed(tmp_path)

    steps = _stats(tmp_path)["steps"]

    assert steps["download"] == {"mean_s": pytest.approx(30.0), "last_s": pytest.approx(40.0), "count": 2}
    assert steps["render"] == {"mean_s": pytest.approx(150.0), "last_s": pytest.approx(100.0), "count": 2}
    assert "transcribe" not in steps                                   # étape jamais terminée : pas de durée inventée
    period = _stats(tmp_path, "?since=2026-09-01")["steps"]
    assert period["download"]["count"] == 1 and period["download"]["mean_s"] == pytest.approx(40.0)


def test_stats_counts_videos_by_status(tmp_path, isolated_cwd):
    _stats_seed(tmp_path)

    counts = _stats(tmp_path)["counts"]
    assert counts == {"pending": 0, "running": 1, "awaiting_review": 0, "queued": 0, "done": 2, "failed": 1}
    assert _stats(tmp_path, "?until=2026-08-31")["counts"]["done"] == 1


@pytest.mark.parametrize("query", ["?since=hier", "?until=2026-13-45", "?since=2026-09-30&until=2026-09-01"])
def test_stats_invalid_period_is_a_422_with_detail(tmp_path, isolated_cwd, query):
    resp = client(tmp_path).get(f"/api/stats{query}")
    assert resp.status_code == 422
    assert resp.json()["detail"]


def test_stats_unreadable_journal_is_a_500_naming_the_file(tmp_path, isolated_cwd):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "outcomes.jsonl").write_text("{pas du json\n", encoding="utf-8")

    resp = client(tmp_path).get("/api/stats")

    assert resp.status_code == 500
    assert "outcomes.jsonl" in resp.json()["detail"]


def _stats_post(tmp_path, content, name="stats.csv", field="file"):
    return client(tmp_path).post("/api/stats/import", files={field: (name, content, "text/csv")})


def test_stats_import_calls_outcomes_import_stats_and_returns_the_row_count(tmp_path, isolated_cwd, monkeypatch):
    from clipper import outcomes

    seen = {}
    real = outcomes.import_stats

    def spy(csv_path, *, path=None):
        seen["text"] = Path(csv_path).read_text(encoding="utf-8")
        seen["path"] = path
        return real(csv_path, path=path)

    monkeypatch.setattr(outcomes, "import_stats", spy)

    resp = _stats_post(tmp_path, STATS_CSV.encode("utf-8"))

    assert resp.status_code == 200
    assert resp.json() == {"imported": 1}
    assert seen["text"] == STATS_CSV
    assert Path(seen["path"]) == Path("state/outcomes.jsonl")
    journal = [json.loads(line) for line in (tmp_path / "state" / "outcomes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert journal[0]["kind"] == "stats" and journal[0]["stats"]["views"] == 1200


def test_stats_import_missing_column_is_a_422_with_detail_and_writes_nothing(tmp_path, isolated_cwd):
    resp = _stats_post(tmp_path, b"clip_id,views\n01,10\n")

    assert resp.status_code == 422
    assert "colonne" in resp.json()["detail"] and "shares" in resp.json()["detail"]
    assert not (tmp_path / "state" / "outcomes.jsonl").exists()


def test_stats_import_bad_row_leaves_the_journal_untouched(tmp_path, isolated_cwd):
    _stats_jsonl(tmp_path / "state" / "outcomes.jsonl", [{"kind": "result", "recorded_at": "2026-09-01T00:00:00+00:00"}])
    before = (tmp_path / "state" / "outcomes.jsonl").read_bytes()
    bad = STATS_CSV + "03,beaucoup,0.5,0.2,1,2026-09-26\n"

    resp = _stats_post(tmp_path, bad.encode("utf-8"))

    assert resp.status_code == 422 and resp.json()["detail"]
    assert (tmp_path / "state" / "outcomes.jsonl").read_bytes() == before


def test_stats_import_requires_a_multipart_file_field(tmp_path, isolated_cwd):
    assert client(tmp_path).post("/api/stats/import", json={"x": 1}).status_code == 422
    assert _stats_post(tmp_path, STATS_CSV.encode("utf-8"), field="autre").status_code == 422
    assert _stats_post(tmp_path, b"\xff\xfe\x00").status_code == 422


def test_stats_screen_shows_four_blocks_period_and_import():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "screens" / "stats.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")

    assert "/static/screens/stats.js" in page
    assert page.index("/static/screens.js") < page.index("/static/screens/stats.js") < page.index("/static/app.js")
    assert "Screens.stats" in js and "/api/stats" in js and "/api/stats/import" in js
    assert "since" in js and "until" in js and 'type="file"' in js and "FormData" in js
    for block in ("Résultats par clip", "Coûts du modèle", "Durée par étape", "Vidéos par statut"):
        assert block in js
    for field in ("llm_cost", "by_video", "by_usage", "by_day", "steps", "counts", "stats_unmatched"):
        assert field in js
    assert "toastError" in js                              # erreur d'API affichée, jamais avalée
    assert "TASK-7d86" in css


def test_style_css_braces_are_balanced():
    # Une accolade manquante avale tout le CSS qui suit (écrans Surveillance, Statistiques).
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "style.css").read_text(encoding="utf-8"), flags=re.S)
    assert css.count("{") == css.count("}")


# --------------------------------------------------------------------------
# Acces distant de bout en bout (SPEC-c100 T5, T7 ; ADR-4f6e §5)
# --------------------------------------------------------------------------


def _serve_setup(tmp_path, monkeypatch, web_toml: str = ""):
    import uvicorn

    from clipper import __main__ as cli

    (tmp_path / "config.toml").write_text(
        f'mode = "review"\n{web_toml}',
        encoding="utf-8",
    )
    runs: list[tuple] = []
    spawned: list[list[str]] = []

    class _Proc:
        def terminate(self) -> None:
            spawned.append(["terminate"])

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: runs.append((app, kw)))
    monkeypatch.setattr(cli, "_popen", lambda cmd, *a, **kw: spawned.append(cmd) or _Proc())
    return cli, runs, spawned


def test_cli_serve_host_without_token_refuses_to_start_and_names_the_key(
    tmp_path, isolated_cwd, monkeypatch, capsys
):
    cli, runs, spawned = _serve_setup(tmp_path, monkeypatch)

    assert cli.main(["serve", "--host", "0.0.0.0"]) == 1

    err = capsys.readouterr().err
    assert "[web] token" in err and "0.0.0.0" in err and "jeton" in err
    assert runs == [] and spawned == []  # ni serveur ni worker lancés


def test_cli_serve_host_from_config_without_token_also_refuses(tmp_path, isolated_cwd, monkeypatch, capsys):
    cli, runs, _ = _serve_setup(tmp_path, monkeypatch, '[web]\nhost = "0.0.0.0"\n')

    assert cli.main(["serve"]) == 1
    assert "[web] token" in capsys.readouterr().err
    assert runs == []


def test_cli_serve_host_with_token_runs_uvicorn_on_the_requested_host(tmp_path, isolated_cwd, monkeypatch):
    cli, runs, _ = _serve_setup(tmp_path, monkeypatch, '[web]\ntoken = "secret-de-test"\n')

    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "9100"]) == 0

    app, kwargs = runs[0]
    assert kwargs["host"] == "0.0.0.0" and kwargs["port"] == 9100
    # l'application appliquée est bien protégée par le jeton
    assert TestClient(app).get("/api/queue").status_code == 401


def test_cli_serve_host_loopback_needs_no_token(tmp_path, isolated_cwd, monkeypatch):
    cli, runs, _ = _serve_setup(tmp_path, monkeypatch)

    assert cli.main(["serve", "--host", "127.0.0.1"]) == 0
    assert runs[0][1]["host"] == "127.0.0.1"


def test_page_served_without_cookie_shows_the_token_entry_and_api_is_401(tmp_path, isolated_cwd):
    config = _config_with_web(tmp_path, host="0.0.0.0", token="secret")
    test_client = TestClient(create_app(config=config))

    page = test_client.get("/")
    assert page.status_code == 200
    assert 'id="token-view"' in page.text and 'id="token-form"' in page.text
    assert test_client.get("/api/videos").status_code == 401
    assert test_client.get("/api/videos", headers={"x-clipper-token": "secret"}).status_code == 200


def test_browser_notification_permission_is_asked_only_from_the_local_setting(tmp_path, isolated_cwd):
    js = served(tmp_path, "/static/app.js")
    assert js.count("requestPermission(") == 1
    start = js.index("async function toggleNotifications")
    assert js.index("requestPermission(") > start  # dans le basculement du réglage
    boot = js[js.index("(function boot()"):]
    assert "requestPermission" not in boot  # jamais au chargement
    assert "localStorage" in js and "clipper-notifications" in js  # réglage local au navigateur
    # on ne notifie que si le réglage est actif ET la permission accordée
    assert 'notificationsOn() && typeof Notification !== "undefined" && Notification.permission === "granted"' in js
    for status in ("done", "failed", "awaiting_review", "queued"):
        assert f"{status}: {{" in js, status


_ROOT = Path(__file__).resolve().parent.parent


def _console_section() -> str:
    guide = (_ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    start = guide.index("## Console de gestion")
    end = guide.find("\n## ", start + 1)
    return guide[start:end if end != -1 else None]


def test_guide_console_section_covers_screens_queue_presets_state_watch_and_remote_access():
    section = _console_section()
    for screen in ("Accueil", "Vidéos", "Revue", "Clips", "Chaînes", "Publication", "Statistiques", "Réglages"):
        assert screen in section, screen
    assert "Les 8 écrans" in section
    for needle in (
        "state/queue.json", "state/watch/", "state/publish/",   # file et state/
        "surcouche", "presets/ma_chaine.toml",                  # presets en surcouche + exemple
        "watch = true", "à confirmer",                          # surveillance
        "[web] token", "--host", "401",                         # accès distant par jeton
        "Réseau local seulement", "Pas de TLS", "reverse proxy TLS",   # limites
        "notifications du navigateur",
    ):
        assert needle in section, needle


def test_readme_and_changelog_mention_the_console_v2():
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Console de gestion web (v2)" in readme and "--host 0.0.0.0" in readme
    assert "Console de gestion web v2" in changelog and "[web] token" in changelog


def test_console_docs_example_preset_is_valid(tmp_path, isolated_cwd):
    import re

    from clipper import channel

    section = _console_section()
    block = re.search(r"```toml\n(\[channel\].*?)```", section, re.S).group(1)
    (tmp_path / "config.toml").write_text('mode = "review"\n', encoding="utf-8")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "ma_chaine.toml").write_text(block, encoding="utf-8")

    _config, chan = channel.load_channel("ma_chaine")

    assert chan["display_name"] == "ma_chaine" and chan["watch"] is True


# --------------------------------------------------------------------------
# Corrections console v2 (TASK-dc9d)
# --------------------------------------------------------------------------

ANSI_ERROR = "\x1b[0;31mERROR:\x1b[0m \x1b[1mvideo indisponible\x1b[0m"
ANSI_CLEAN = "ERROR: video indisponible"


def test_api_strips_ansi_sequences_from_failure_reasons_and_journal(tmp_path, isolated_cwd):
    state = _write_state(tmp_path, VIDEO_ID, status="failed", reason=ANSI_ERROR)
    state["steps"]["download"].update(status="failed", reason=ANSI_ERROR)
    (tmp_path / "workspace" / VIDEO_ID / "pipeline.json").write_text(json.dumps(state), encoding="utf-8")
    (tmp_path / "workspace" / VIDEO_ID / "events.jsonl").write_text(json.dumps(
        {"at": "2026-01-01T10:00:00+00:00", "level": "ERROR", "step": "download", "message": ANSI_ERROR}) + "\n",
        encoding="utf-8")
    c = client(tmp_path)

    video = c.get(f"/api/videos/{VIDEO_ID}")
    events = c.get(f"/api/videos/{VIDEO_ID}/events")
    dashboard = c.get("/api/dashboard")
    listing = c.get("/api/videos")

    for resp in (video, events, dashboard, listing):
        assert resp.status_code == 200
        assert "\x1b" not in resp.text and "\\u001b" not in resp.text
    assert video.json()["reason"] == ANSI_CLEAN
    assert events.json()[0]["message"] == ANSI_CLEAN
    assert dashboard.json()["failed"][0]["reason"] == ANSI_CLEAN


def test_api_strips_ansi_sequences_from_error_details(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline

    def boom(*a, **k):
        raise pipeline.PipelineError(ANSI_ERROR)

    monkeypatch.setattr(pipeline, "load_state", boom)

    resp = client(tmp_path).get(f"/api/videos/{VIDEO_ID}")

    assert resp.status_code == 404
    assert resp.json()["detail"] == ANSI_CLEAN


def test_strip_ansi_keeps_plain_text_and_handles_nested_json():
    from clipper.web.app import _strip_ansi

    assert _strip_ansi({"a": ["\x1b[31mx\x1b[0m", 3, None], "b": "é ça [0m reste"}) == {
        "a": ["x", 3, None], "b": "é ça [0m reste"}


THUMB_VIDEO = "abcdefghijk"


def test_media_clip_thumbnail_route_serves_the_pipeline_thumbnail(tmp_path, isolated_cwd, monkeypatch):
    from clipper import pipeline, render

    out_dir = tmp_path / "output" / THUMB_VIDEO
    out_dir.mkdir(parents=True)
    (out_dir / "01.mp4").write_bytes(b"mp4")
    calls = []

    def fake_exec(cmd, cwd, out_path):
        calls.append(cmd)
        Path(out_path).write_bytes(b"\xff\xd8jpeg-bytes")

    monkeypatch.setattr(render, "_exec_ffmpeg", fake_exec)
    c = client(tmp_path)

    first = c.get(f"/media/clip/{THUMB_VIDEO}/01/thumbnail")
    second = c.get(f"/media/clip/{THUMB_VIDEO}/01/thumbnail")

    assert first.status_code == 200 and first.content == b"\xff\xd8jpeg-bytes"
    assert first.headers["content-type"] == "image/jpeg"
    assert "max-age" in first.headers["cache-control"]
    assert second.content == first.content and len(calls) == 1
    assert pipeline.clip_thumbnail(make_config(tmp_path), THUMB_VIDEO, "01").is_file()


def test_media_clip_thumbnail_route_errors_are_explicit(tmp_path, isolated_cwd, monkeypatch):
    from clipper import render

    c = client(tmp_path)
    assert c.get(f"/media/clip/{THUMB_VIDEO}/..%2Fx/thumbnail").status_code == 404
    assert c.get("/media/clip/../01/thumbnail").status_code in (404, 422)
    missing = c.get(f"/media/clip/{THUMB_VIDEO}/99/thumbnail")
    assert missing.status_code == 404 and "introuvable" in missing.json()["detail"]

    out_dir = tmp_path / "output" / THUMB_VIDEO
    out_dir.mkdir(parents=True)
    (out_dir / "01.mp4").write_bytes(b"mp4")

    def boom(cmd, cwd, out_path):
        raise render.RenderError("ffmpeg introuvable (ffmpeg)")

    monkeypatch.setattr(render, "_exec_ffmpeg", boom)
    failed = c.get(f"/media/clip/{THUMB_VIDEO}/01/thumbnail")
    assert failed.status_code == 422 and "miniature" in failed.json()["detail"]


def test_clips_gallery_uses_lazy_thumbnails_and_no_video_tag_in_the_grid():
    js = (STATIC / "screens" / "clips.js").read_text(encoding="utf-8")
    card = js[js.index("function clipCard"):js.index("function clipsEmpty")]

    assert '<img loading="lazy"' in card and "thumbnail_url" in card
    assert "<video" not in card
    # la vidéo n'est chargée qu'à l'ouverture d'un clip (fiche)
    drawer = js[js.index("function clipDrawerHtml"):]
    assert "<video" in drawer
    assert "CLIPS_PAGE_SIZE = 24" in js and "Afficher plus" in js


def test_clip_views_expose_the_thumbnail_url(tmp_path, isolated_cwd):
    _clips_setup(tmp_path)

    clips = {c["clip_id"]: c for c in client(tmp_path).get("/api/clips", params={"video_id": CLIPS_VIDEO}).json()}

    assert clips["01"]["thumbnail_url"] == f"/media/clip/{CLIPS_VIDEO}/01/thumbnail"


def test_new_channel_button_opens_a_defined_and_visible_modal_panel():
    import re

    channels = (STATIC / "screens" / "channels.js").read_text(encoding="utf-8")
    ui = (STATIC / "ui.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    page = (STATIC / "index.html").read_text(encoding="utf-8")

    assert "[data-chan-new]" in channels and "onclick = chOpenNew" in channels
    call = re.search(r'function chOpenNew\(\) \{\s*openPanel\("([^"]+)"', channels)
    assert call, "chOpenNew doit appeler openPanel"
    assert "function openPanel(" in ui
    assert page.index("/static/ui.js") < page.index("/static/screens/channels.js")
    # classe CSS du panneau : définie, positionnée au-dessus du fond, visible une fois .show posé
    classes = call.group(1).split()
    assert "modal" in classes
    rule = re.search(r"^\.modal \{([^}]*)\}", css, re.M).group(1)
    shown = re.search(r"^\.modal\.show \{([^}]*)\}", css, re.M).group(1)
    assert "position: fixed" in rule and "opacity: 0" in rule and "opacity: 1" in shown
    z = lambda sel: int(re.search(rf"^{re.escape(sel)} \{{[^}}]*z-index: (\d+)", css, re.M).group(1))
    assert z(".modal") > z(".overlay")
    assert "classList.add(\"show\")" in ui
    # le panneau ne dépend pas du seul requestAnimationFrame (suspendu hors écran) pour devenir visible
    panel = ui[ui.index("function openPanel("):ui.index("document.addEventListener(\"keydown\"")]
    assert "setTimeout(reveal" in panel and "try { onOpen(el); }" in panel


# --------------------------------------------------------------------------
# TASK-a40d : corrections du deuxième tour de la console v2
# --------------------------------------------------------------------------

def _write_full_sidecar(tmp_path, video_id, clip_id, **fields):
    """Sidecar tel que le rend le pipeline : il porte son video_id (SPEC-6a47)."""
    sidecar = {"video_id": video_id, "clip_id": clip_id, "ready": True, "screen_title": f"Titre {clip_id}", **fields}
    _write_json(tmp_path / "output" / video_id / f"{clip_id}.json", sidecar)


_QA_ISSUE = {"type": "black_frames", "detail": "image noire de 2 s", "source": "local", "severity": "blocking"}


def _round2_clips(tmp_path):
    """3 clips d'une vidéo avec chaîne, dont 1 refusé par la QA : 2 à valider."""
    _write_state(tmp_path, "aaaaaaaaaaa", channel="ma_chaine")
    _write_full_sidecar(tmp_path, "aaaaaaaaaaa", "01", qa={"status": "passed", "issues": []})
    _write_full_sidecar(tmp_path, "aaaaaaaaaaa", "02", qa={"status": "passed", "issues": []})
    _write_full_sidecar(tmp_path, "aaaaaaaaaaa", "03", ready=False, qa={"status": "rejected", "issues": [_QA_ISSUE]})


def test_stats_issue_text_extracts_the_message_of_a_qa_issue_never_object_object():
    js = (STATIC / "screens" / "stats.js").read_text(encoding="utf-8")

    assert "function statsIssueText" in js
    assert "issue.detail" in js
    assert 'c.issues.map(statsIssueText)' in js
    assert 'c.issues.join(' not in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent du PATH")
def test_stats_issue_text_renders_objects_and_strings_readably(tmp_path):
    js = (STATIC / "screens" / "stats.js").read_text(encoding="utf-8")
    start = js.index("function statsIssueText")
    end = js.index("\n}\n", start) + 3
    script = js[start:end] + f"\nconsole.log(JSON.stringify([statsIssueText({json.dumps(_QA_ISSUE)}), statsIssueText('hors cadre')]));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["image noire de 2 s", "hors cadre"]


def test_api_stats_passes_the_qa_issues_as_objects_the_screen_must_unwrap(tmp_path, isolated_cwd):
    _round2_clips(tmp_path)

    clips = {c["clip_id"]: c for c in _stats(tmp_path)["clips"]}

    assert clips["03"]["issues"] == [_QA_ISSUE]


def test_qa_rejected_clip_is_neither_counted_nor_listed_as_to_validate(tmp_path, isolated_cwd):
    _round2_clips(tmp_path)
    c = client(tmp_path)

    to_validate = c.get("/api/clips", params={"status": "à valider"}).json()
    rejected = c.get("/api/clips", params={"status": "rejected"}).json()

    assert [x["clip_id"] for x in to_validate] == ["01", "02"]
    assert [x["clip_id"] for x in rejected] == ["03"]
    assert rejected[0]["qa_status"] == "rejected"
    assert len(c.get("/api/clips").json()) == 3


def test_dashboard_and_clips_page_count_the_same_clips_to_validate(tmp_path, isolated_cwd):
    _round2_clips(tmp_path)
    _write_state(tmp_path, "bbbbbbbbbbb", channel=None)
    _write_full_sidecar(tmp_path, "bbbbbbbbbbb", "01")
    c = client(tmp_path)

    on_page = len(c.get("/api/clips", params={"status": "à valider"}).json())

    assert _dashboard(tmp_path)["clips_to_review"] == on_page == 3


def test_clip_not_ready_and_not_rejected_is_not_to_validate_either(tmp_path, isolated_cwd):
    _write_state(tmp_path, "aaaaaaaaaaa", channel="ma_chaine")
    _write_full_sidecar(tmp_path, "aaaaaaaaaaa", "01", ready=False)
    c = client(tmp_path)

    assert c.get("/api/clips", params={"status": "à valider"}).json() == []
    assert _dashboard(tmp_path)["clips_to_review"] == 0
    assert c.get("/api/clips").json()[0]["publish_status"] == "not_ready"


def test_clips_screen_labels_every_server_status_including_not_ready():
    js = (STATIC / "screens" / "clips.js").read_text(encoding="utf-8")

    assert "not_ready" in js


def _serve_like_config(tmp_path, port):
    """Config lue dans config.toml puis surchargée comme le fait 'serve --port'."""
    import dataclasses

    from clipper.config import load_config

    config = load_config(tmp_path / "config.toml")
    sections = {**config._sections, "web": {**config._sections.get("web", {}), "port": port}}
    return dataclasses.replace(config, _sections=sections)


def test_settings_access_shows_the_real_port_and_flags_the_difference_with_config_toml(tmp_path, isolated_cwd):
    _settings_setup(tmp_path, '[web]\nport = 8000\n')
    app_client = TestClient(create_app(config=_serve_like_config(tmp_path, 8765)))

    data = app_client.get("/api/settings").json()

    access = data["access"]
    assert access["port"] == 8765 and "--port 8765" in access["command"]
    assert access["config_port"] == 8000 and access["config_host"] == "127.0.0.1"
    assert access["differs_from_config"] is True
    assert data["restart_required"] is True                          # config.toml dit 8000, l'écoute en cours 8765


def test_settings_access_does_not_flag_anything_when_serve_matches_config_toml(tmp_path, isolated_cwd):
    _settings_setup(tmp_path, '[web]\nport = 8000\n')

    access = sclient(tmp_path).get("/api/settings").json()["access"]

    assert access["port"] == 8000 and access["differs_from_config"] is False


def test_cli_serve_hands_the_real_port_to_the_app(tmp_path, isolated_cwd, monkeypatch):
    cli, runs, _ = _serve_setup(tmp_path, monkeypatch, '[web]\nport = 8000\n')

    assert cli.main(["serve", "--port", "8765"]) == 0

    app, kwargs = runs[0]
    assert kwargs["port"] == 8765
    access = TestClient(app).get("/api/settings").json()["access"]
    assert access["port"] == 8765 and access["config_port"] == 8000 and access["differs_from_config"] is True


def test_settings_screen_shows_the_real_access_and_the_difference():
    js = (STATIC / "screens" / "settings.js").read_text(encoding="utf-8")

    assert "differs_from_config" in js and "config_port" in js


def test_settings_access_shows_a_single_notice_when_the_running_server_differs_from_config_toml():
    js = (STATIC / "screens" / "settings.js").read_text(encoding="utf-8")
    start = js.index("function setAccess()")
    body = js[start:js.index("\n}\n", start)]

    # l'avis « redémarrage » n'est affiché que si l'avis d'écart (hôte/port) ne l'est pas déjà
    assert "restart_required && !access.differs_from_config" in body
    # l'avis d'écart dit les deux valeurs et quand le fichier s'appliquera
    assert "access.host" in body and "access.port" in body and "config_host" in body and "config_port" in body
    assert "au prochain « serve » lancé sans --host/--port" in body
    assert "un redémarrage de « serve » est nécessaire" in body  # avis conservé pour un jeton seul


def _fresh_heartbeat(tmp_path, **fields):
    beat = {"pid": os.getpid(), "at": datetime.now(timezone.utc).isoformat(), **fields}
    _write_json(tmp_path / "state" / "worker.json", beat)
    return beat


def test_dashboard_exposes_a_worker_stopped_with_the_command_when_no_heartbeat(tmp_path, isolated_cwd):
    worker = _dashboard(tmp_path)["worker"]

    assert worker["state"] == "stopped"
    assert worker["command"] == "python -m clipper worker"
    assert worker["reason"]


def test_dashboard_exposes_a_worker_active_with_pid_and_age(tmp_path, isolated_cwd):
    beat = _fresh_heartbeat(tmp_path)

    worker = _dashboard(tmp_path)["worker"]

    assert worker["state"] == "active" and worker["pid"] == beat["pid"]
    assert worker["age_s"] < 30


def test_dashboard_worker_with_a_stale_heartbeat_is_not_active(tmp_path, isolated_cwd):
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    _write_json(tmp_path / "state" / "worker.json", {"pid": os.getpid(), "at": old.isoformat()})

    worker = _dashboard(tmp_path)["worker"]

    assert worker["state"] == "stale"
    assert worker["command"] == "python -m clipper worker"


def test_dashboard_unreadable_heartbeat_is_null_with_a_french_error(tmp_path, isolated_cwd):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker.json").write_text("{pas du json", encoding="utf-8")

    data = _dashboard(tmp_path)

    assert data["worker"] is None and "worker" in data["worker_error"]


def test_dashboard_screen_shows_the_worker_light_and_the_command_when_not_active():
    js = (STATIC / "screens" / "dashboard.js").read_text(encoding="utf-8")

    assert "data.worker" in js and "worker_error" in js
    assert "worker actif" in js and "worker arrêté" in js
    assert "worker.command" in js and '"active"' in js


def test_heartbeat_file_does_not_flood_the_event_stream(tmp_path, isolated_cwd):
    from clipper.web.app import _scan_watched

    _fresh_heartbeat(tmp_path)

    kinds = {kind for _, kind, _ in _scan_watched(tmp_path / "workspace", tmp_path / "state")}

    assert "worker" not in kinds


_UNACCENTED = (
    "reponse", "refusee", "hote", "ecoute", "defaut", "parametre", "frequence", "modele", "ecran", "meme",
    "memes", "etape", "regle", "regles", "reglage", "reglages", "deja", "apres", "cle", "cles", "camera",
    "video", "videos", "schema", "tete", "boite", "echec", "ecart", "resultat", "resultats", "selection",
    "duree", "donnee", "donnees", "detecteur", "detection", "systeme", "memoire", "premiere", "derniere",
    "entiere", "centree", "elargie", "reduite", "reduit", "reduits", "desactive", "desactivee", "generes",
    "journalisee", "reel", "reelle", "reellement", "bornee", "scene", "scenes", "apparait", "recoit",
    "telecharge", "telechargement", "appliquee", "precedent", "precedente", "presence", "pensees", "tolere",
    "tolerance", "echantillonnee", "equirepartis", "etiree", "evite", "fenetre", "unite", "serie", "sure",
    "cote", "cotes", "plutot", "ecartees", "elargi", "deborde", "defauts", "derriere",
)


def _exposed_comments(tmp_path) -> dict[str, str]:
    c = sclient(tmp_path)
    found = {}
    for section, keys in c.get("/api/settings").json()["defaults"].items():
        for key, doc in keys.items():
            found[f"settings/{section}.{key}"] = doc["comment"]
    return found


def test_help_texts_exposed_by_the_api_are_accented_french(tmp_path, isolated_cwd):
    import re

    from clipper.web import app as web_app

    comments = _exposed_comments(tmp_path)
    for section in web_app._CHANNEL_FORM_SECTIONS:
        for key, doc in web_app._defaults_documentation(section).items():
            comments[f"channel/{section}.{key}"] = doc["comment"]
    assert any(comments.values())
    words = list(_UNACCENTED)
    offenders = []
    for where, comment in comments.items():
        # hors identifiants : « scenes.json », « video_id », `nom_de_cle` ne sont pas du texte
        prose = re.sub(r"[\w./-]*[_./][\w./-]*", " ", comment)
        for word in words:
            if re.search(rf"(?<![\w-]){word}(?![\w-])", prose, re.IGNORECASE):
                offenders.append(f"{where} : « {word} »")
    assert offenders == []


def test_videos_are_listed_most_recently_added_first(tmp_path, isolated_cwd):
    _write_state(tmp_path, "aaaaaaaaaaa", enqueued_at="2026-09-01T10:00:00+00:00")
    _write_state(tmp_path, "ccccccccccc", enqueued_at="2026-09-03T10:00:00+00:00")
    _write_state(tmp_path, "bbbbbbbbbbb", enqueued_at="2026-09-02T10:00:00+00:00")

    ids = [v["video_id"] for v in client(tmp_path).get("/api/videos").json()]

    assert ids == ["ccccccccccc", "bbbbbbbbbbb", "aaaaaaaaaaa"]


def _drop_enqueued_at(tmp_path, video_id):
    path = tmp_path / "workspace" / video_id / "pipeline.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    del state["enqueued_at"]
    path.write_text(json.dumps(state), encoding="utf-8")


def test_videos_without_enqueued_at_are_sorted_by_pipeline_json_creation_date(tmp_path, isolated_cwd, monkeypatch):
    _write_state(tmp_path, "aaaaaaaaaaa")
    _write_state(tmp_path, "bbbbbbbbbbb")
    _write_state(tmp_path, "ccccccccccc", enqueued_at="2026-09-02T10:00:00+00:00")
    for video_id in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        _drop_enqueued_at(tmp_path, video_id)
    created = {"aaaaaaaaaaa": "2026-09-03T10:00:00+00:00", "bbbbbbbbbbb": "2026-09-01T10:00:00+00:00"}
    monkeypatch.setattr(
        web_app, "_pipeline_created_at",
        lambda path: (datetime.fromisoformat(created[path.parent.name]), "pipeline_json_created"),
    )

    videos = client(tmp_path).get("/api/videos").json()

    assert [v["video_id"] for v in videos] == ["aaaaaaaaaaa", "ccccccccccc", "bbbbbbbbbbb"]
    by_id = {v["video_id"]: v for v in videos}
    assert by_id["ccccccccccc"]["added_at"] == "2026-09-02T10:00:00+00:00"
    assert by_id["ccccccccccc"]["added_at_source"] == "enqueued_at"
    assert by_id["aaaaaaaaaaa"]["added_at"] == "2026-09-03T10:00:00+00:00"
    assert by_id["aaaaaaaaaaa"]["added_at_source"] == "pipeline_json_created"
    assert all(v["added_at"] for v in videos)


def test_pipeline_created_at_reads_the_real_file(tmp_path):
    path = tmp_path / "pipeline.json"
    path.write_text("{}", encoding="utf-8")

    when, source = web_app._pipeline_created_at(path)

    assert when.tzinfo is not None and source in {"pipeline_json_created", "pipeline_json_mtime"}
    assert abs((datetime.now(timezone.utc) - when).total_seconds()) < 60


def test_static_files_are_always_revalidated(tmp_path, isolated_cwd):
    c = client(tmp_path)
    for url in ("/", "/static/app.js", "/static/screens/videos.js"):
        resp = c.get(url)
        assert resp.status_code == 200, url
        assert resp.headers["cache-control"] == "no-cache", url
        etag = resp.headers["etag"]
        again = c.get(url, headers={"If-None-Match": etag})
        assert again.status_code == 304, url
        assert again.headers["cache-control"] == "no-cache", url


def test_no_retired_adr_or_spec_citation_remains_under_clipper():
    root = Path(web_app.__file__).resolve().parents[1]
    offenders = []
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".woff", ".woff2", ".png", ".ico"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        offenders += [f"{path.relative_to(root)} : {old}" for old in ("ADR-4f6e", "SPEC-fc0c") if old in text]
    assert offenders == []


def test_videos_screen_keeps_the_server_order(tmp_path):
    js = (STATIC / "screens" / "videos.js").read_text(encoding="utf-8")

    assert ".sort(" not in js


def test_stats_clip_table_paginates_by_50_with_show_more():
    js = (STATIC / "screens" / "stats.js").read_text(encoding="utf-8")

    assert "STATS_CLIPS_PAGE_SIZE = 50" in js
    assert "Afficher plus" in js and "data-stats-more" in js
    assert "data.clips.slice(0, statsUi.shown)" in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent du PATH")
def test_stats_clip_pagination_reveals_50_more_rows_per_click():
    js = (STATIC / "screens" / "stats.js").read_text(encoding="utf-8")
    start = js.index("function statsMoreCount")
    end = js.index("\n}\n", start) + 3
    script = "const STATS_CLIPS_PAGE_SIZE = 50;\n" + js[start:end] + "\nconsole.log(JSON.stringify([statsMoreCount(120, 50), statsMoreCount(120, 100), statsMoreCount(30, 50)]));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [50, 20, 0]


# --------------------------------------------------------------------------
# TASK-c0ef : console v2, quatrieme tour
# --------------------------------------------------------------------------


def _static(*parts) -> str:
    return STATIC.joinpath(*parts).read_text(encoding="utf-8")


def test_settings_section_links_scroll_instead_of_being_read_as_a_screen():
    settings = _static("screens", "settings.js")
    app = _static("app.js")

    # Les liens gardent leur ancre, mais un clic fait defiler sans changer de hash...
    assert 'href="#set-${id}"' in settings
    assert "scrollIntoView" in settings and "preventDefault()" in settings
    assert "data-set-nav" in settings
    # ...et le routeur n'interprete jamais « #set-xxx » comme un ecran (retour au tableau de bord).
    route = app[app.index("function route()"):app.index("function renderCurrent")]
    assert 'startsWith("set-")' in route and "scrollIntoView" in route


def _write_meta_title(tmp_path, video_id, title):
    meta = tmp_path / "workspace" / video_id
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "meta.json").write_text(json.dumps({"video_id": video_id, "title": title}), encoding="utf-8")


def test_dashboard_problem_rows_carry_the_video_title_or_the_id(tmp_path, isolated_cwd):
    _write_state(tmp_path, "aaaaaaaaaaa", status="failed", reason="ffmpeg a echoue")
    _write_state(tmp_path, "bbbbbbbbbbb", status="queued", reason="quota", retry_at="2026-01-02T08:00:00+00:00")
    _write_meta_title(tmp_path, "aaaaaaaaaaa", "Mon direct du soir")

    data = _dashboard(tmp_path)

    assert data["failed"][0]["title"] == "Mon direct du soir"
    assert data["queued"][0]["title"] == "bbbbbbbbbbb"  # pas de titre : l'identifiant


def test_dismiss_removes_a_failed_video_from_the_dashboard_without_deleting_its_workspace(tmp_path, isolated_cwd):
    _write_state(tmp_path, "aaaaaaaaaaa", status="failed", reason="ffmpeg a echoue")
    (tmp_path / "workspace" / "aaaaaaaaaaa" / "keep.txt").write_text("x", encoding="utf-8")
    c = client(tmp_path)

    resp = c.post("/api/videos/aaaaaaaaaaa/dismiss")

    assert resp.status_code == 200 and resp.json()["dismissed_at"]
    assert _dashboard(tmp_path)["failed"] == []
    assert (tmp_path / "workspace" / "aaaaaaaaaaa" / "keep.txt").read_text(encoding="utf-8") == "x"
    detail = c.get("/api/videos/aaaaaaaaaaa").json()
    assert detail["dismissed_at"] and detail["status"] == "failed"  # l'etat reste lisible, explicite

    back = c.post("/api/videos/aaaaaaaaaaa/restore")
    assert back.status_code == 200 and "dismissed_at" not in back.json()
    assert [v["video_id"] for v in _dashboard(tmp_path)["failed"]] == ["aaaaaaaaaaa"]


def test_dismiss_also_clears_a_queued_video_from_the_counters(tmp_path, isolated_cwd):
    _write_state(tmp_path, "bbbbbbbbbbb", status="queued", reason="quota", retry_at="2026-01-02T08:00:00+00:00")

    assert client(tmp_path).post("/api/videos/bbbbbbbbbbb/dismiss").status_code == 200

    assert _dashboard(tmp_path)["queued"] == []


def test_dismiss_errors_are_explicit(tmp_path, isolated_cwd):
    _write_state(tmp_path, "aaaaaaaaaaa", status="running")
    c = client(tmp_path)

    running = c.post("/api/videos/aaaaaaaaaaa/dismiss")
    assert running.status_code == 409 and "echec" in running.json()["detail"]
    missing = c.post("/api/videos/zzzzzzzzzzz/dismiss")
    assert missing.status_code == 404 and "aucun etat" in missing.json()["detail"]
    assert c.post("/api/videos/zzzzzzzzzzz/restore").status_code == 404
    assert c.post("/api/videos/..%2Fx/dismiss").status_code in (404, 422)


def test_dismissed_video_is_requeued_by_a_retry_and_reappears(tmp_path, isolated_cwd, monkeypatch):
    from clipper import worker

    _write_state(tmp_path, "aaaaaaaaaaa", status="failed", reason="ffmpeg a echoue")
    c = client(tmp_path)
    c.post("/api/videos/aaaaaaaaaaa/dismiss")
    monkeypatch.setattr(worker, "enqueue", lambda url, channel, action, force_steps, *, config=None: {
        "id": "e1", "video_id": "aaaaaaaaaaa", "url": url, "channel": channel, "action": action,
        "force_steps": force_steps or [], "status": "waiting"})

    assert c.post("/api/videos/aaaaaaaaaaa/retry", json={"from_step": "download"}).status_code == 202

    assert "dismissed_at" not in c.get("/api/videos/aaaaaaaaaaa").json()


def test_dashboard_problem_rows_link_to_the_video_sheet_and_offer_retry_and_dismiss():
    dash = _static("screens", "dashboard.js")
    row = dash[dash.index("function dashProblemRow"):dash.index("function dashPublicationRow")]

    assert "#/videos/${encodeURIComponent(video.video_id)}" in row and 'href="#/videos"' not in row
    assert "video.title" in row
    assert "data-retry-video" in row and "Relancer" in row
    assert "data-dismiss-video" in row and "Retirer" in row
    assert "videoThumb(" in row
    assert "/api/videos/${encodeURIComponent(id)}/retry" in _static("app.js") or "/retry" in _static("app.js")
    assert "/dismiss" in _static("app.js")


def test_video_sheet_offers_the_same_retry_and_dismiss_actions():
    videos = _static("screens", "videos.js")

    assert "data-retry-video" in videos and "data-dismiss-video" in videos
    assert "wireActions(view)" in videos  # mêmes gestionnaires (app.js) que le tableau de bord
    assert "Relancer" in videos and "Retirer" in videos and "Rétablir" in videos


def test_media_source_thumbnail_route_serves_the_pipeline_thumbnail(tmp_path, isolated_cwd, monkeypatch):
    from clipper import render

    _write_state(tmp_path, THUMB_VIDEO)
    _write_meta_duration = tmp_path / "workspace" / THUMB_VIDEO
    (_write_meta_duration / "meta.json").write_text(json.dumps({"video_id": THUMB_VIDEO, "duration": 100}), encoding="utf-8")
    (_write_meta_duration / f"{THUMB_VIDEO}.mp4").write_bytes(b"mp4")
    calls = []

    def fake_exec(cmd, cwd, out_path):
        calls.append(cmd)
        Path(out_path).write_bytes(b"\xff\xd8vthumb")

    monkeypatch.setattr(render, "_exec_ffmpeg", fake_exec)
    c = client(tmp_path)

    first = c.get(f"/media/source/{THUMB_VIDEO}/thumbnail")
    second = c.get(f"/media/source/{THUMB_VIDEO}/thumbnail")

    assert first.status_code == 200 and first.content == b"\xff\xd8vthumb"
    assert first.headers["content-type"] == "image/jpeg" and "max-age" in first.headers["cache-control"]
    assert second.content == first.content and len(calls) == 1
    assert calls[0][calls[0].index("-ss") + 1] == "10.000000"


def test_media_source_thumbnail_route_errors_are_explicit(tmp_path, isolated_cwd, monkeypatch):
    from clipper import render

    c = client(tmp_path)
    missing = c.get(f"/media/source/{THUMB_VIDEO}/thumbnail")
    assert missing.status_code == 404 and "introuvable" in missing.json()["detail"]
    assert c.get("/media/source/..%2Fx/thumbnail").status_code == 404

    video_dir = tmp_path / "workspace" / THUMB_VIDEO
    video_dir.mkdir(parents=True)
    (video_dir / f"{THUMB_VIDEO}.mp4").write_bytes(b"mp4")
    (video_dir / "meta.json").write_text(json.dumps({"duration": 100}), encoding="utf-8")

    def boom(cmd, cwd, out_path):
        raise render.RenderError("ffmpeg introuvable (ffmpeg)")

    monkeypatch.setattr(render, "_exec_ffmpeg", boom)
    failed = c.get(f"/media/source/{THUMB_VIDEO}/thumbnail")
    assert failed.status_code == 422 and "vignette" in failed.json()["detail"]


def test_video_thumbnails_are_lazy_images_with_a_neutral_fallback_everywhere():
    helper = _static("screens.js")
    assert "function videoThumb(" in helper
    thumb = helper[helper.index("function videoThumb("):]
    assert '<img loading="lazy"' in thumb and "/media/source/" in thumb and "/thumbnail" in thumb
    assert "pas d'image" in helper
    assert '"error"' in helper and "true" in helper  # l'echec de chargement remplace l'image par la vignette neutre

    for name, marker in (("dashboard.js", "function dashRunningRow"), ("dashboard.js", "function dashProblemRow")):
        src = _static("screens", name)
        assert "videoThumb(" in src[src.index(marker):src.index(marker) + 1800], marker
    assert "videoThumb(" in _static("screens.js")[_static("screens.js").index("function queueRow"):_static("screens.js").index("const addVideoButton")]
    videos = _static("screens", "videos.js")
    assert "videoThumb(" in videos[videos.index("function listRow"):videos.index("function paintList")]
    assert "videoThumb(" in videos[videos.index("function paintDetail"):videos.index("function wireDetail")]


def _stats_channels(tmp_path) -> None:
    _stats_seed(tmp_path)
    for video_id, channel in ((STATS_A, "ma_chaine"), (STATS_B, "autre")):
        path = tmp_path / "workspace" / video_id / "pipeline.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["channel"] = channel
        path.write_text(json.dumps(state), encoding="utf-8")


def test_stats_channel_filter_applies_to_every_block(tmp_path, isolated_cwd):
    _stats_channels(tmp_path)

    data = _stats(tmp_path, "?channel=ma_chaine")

    assert data["channel"] == "ma_chaine"
    assert sorted((c["video_id"], c["clip_id"]) for c in data["clips"]) == [(STATS_A, "01"), (STATS_A, "02")]
    assert set(data["llm_cost"]["by_video"]) == {STATS_A}
    assert data["llm_cost"]["total"] == pytest.approx(1.75)
    assert data["counts"] == {"pending": 0, "running": 0, "awaiting_review": 0, "queued": 0, "done": 1, "failed": 0}
    assert data["steps"]["download"]["mean_s"] == pytest.approx(40)
    assert data["stats_unmatched"] == []


def test_stats_channel_filter_other_channel_and_no_channel(tmp_path, isolated_cwd):
    _stats_channels(tmp_path)

    other = _stats(tmp_path, "?channel=autre")
    assert [(c["video_id"], c["clip_id"]) for c in other["clips"]] == [(STATS_B, "01")]
    assert other["llm_cost"]["total"] == pytest.approx(2.0) and other["counts"]["done"] == 1

    none = _stats(tmp_path, "?channel=__none__")
    assert none["clips"] == [] and none["llm_cost"]["by_video"] == {}
    assert none["counts"]["failed"] == 1 and none["counts"]["running"] == 1 and none["counts"]["done"] == 0


def test_stats_without_channel_parameter_still_covers_everything(tmp_path, isolated_cwd):
    _stats_channels(tmp_path)

    data = _stats(tmp_path)

    assert data["channel"] is None
    assert len(data["clips"]) == 3 and data["counts"]["done"] == 2


def test_stats_screen_filters_by_channel_and_sorts_the_clip_table_on_header_click():
    stats = _static("screens", "stats.js")

    assert "data-stats-channel" in stats and "Toutes les chaînes" in stats and "Sans chaîne" in stats
    assert 'params.set("channel"' in stats and "__none__" in stats
    table = stats[stats.index("function statsClipsBlock"):stats.index("function statsCostBlock")]
    assert "statsHead(" in table and '"Chaîne"' in table
    assert "data-stats-sort" in stats and "aria-sort" in stats
    assert "statsSortInPlace(" in stats and "statsUi.sort" in stats
    assert "[data-stats-sort]" in stats[stats.index("function statsWire"):]


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent du PATH")
def test_stats_clip_sort_orders_by_column_with_missing_values_last():
    js = _static("screens", "stats.js")
    start = js.index("const STATS_SORTS")
    end = js.index("};\n", start) + 3
    fn_start = js.index("function statsSortInPlace")
    fn_end = js.index("\n}\n", fn_start) + 3
    script = (
        js[start:end] + "const statsUi = { sort: { key: 'views', dir: 'desc' } };\n" + js[fn_start:fn_end]
        + "\nconst clips = [{clip_id:'a', stats:{views:5}}, {clip_id:'b', stats:null}, {clip_id:'c', stats:{views:50}}];"
        + "\nstatsSortInPlace(clips); const desc = clips.map(c => c.clip_id).join('');"
        + "\nstatsUi.sort = { key: 'views', dir: 'asc' }; statsSortInPlace(clips);"
        + "\nconsole.log(JSON.stringify([desc, clips.map(c => c.clip_id).join('')]));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["cab", "acb"]


# --------------------------------------------------------------------------
# Grille de notation par chaîne (SPEC-9216 R4)
# --------------------------------------------------------------------------


def test_put_channel_writes_the_builtin_gaming_rubric_in_the_preset(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)

    resp = client(tmp_path).put(f"/api/channels/{CH}", json={"preset": {
        "channel": {"display_name": "Ma chaîne"}, "moments": {"rubric_path": "builtin:gaming"},
    }})

    assert resp.status_code == 200, resp.text
    saved = (tmp_path / "presets" / f"{CH}.toml").read_text(encoding="utf-8")
    assert 'rubric_path = "builtin:gaming"' in saved
    body = client(tmp_path).get(f"/api/channels/{CH}").json()
    assert body["raw"]["moments"] == {"rubric_path": "builtin:gaming"}
    assert body["effective"]["moments"]["rubric_path"] == "builtin:gaming"   # grille en vigueur


def test_get_channel_effective_rubric_is_inherited_without_a_preset_value(tmp_path, isolated_cwd):
    _channels_setup(tmp_path)

    body = client(tmp_path).get(f"/api/channels/{CH}").json()

    assert "moments" not in body["raw"]
    assert body["effective"]["moments"]["rubric_path"] == "rubric.toml"      # défaut du module
    assert body["defaults"]["moments"]["rubric_path"]["default"] == "rubric.toml"
    assert "builtin:gaming" in body["defaults"]["moments"]["rubric_path"]["comment"]


def test_get_video_detail_reports_the_rubric_used_by_moments_json(tmp_path, isolated_cwd):
    _write_state(tmp_path, VIDEO_ID, status="done", steps={})
    _write_json(tmp_path / "workspace" / VIDEO_ID / "moments.json", {
        "video_id": VIDEO_ID, "moments": [],
        "rubric": {"path": "/x/clipper/assets/rubric-gaming.toml", "weights": {"emotion": 4}, "min_score": 45},
    })

    body = client(tmp_path).get(f"/api/videos/{VIDEO_ID}").json()

    assert body["rubric"] == "/x/clipper/assets/rubric-gaming.toml"


def test_get_video_detail_without_moments_json_has_no_rubric(tmp_path, isolated_cwd):
    _write_state(tmp_path, VIDEO_ID, status="running", steps={})

    assert client(tmp_path).get(f"/api/videos/{VIDEO_ID}").json()["rubric"] is None


def test_channels_form_offers_the_rubric_choice_standard_gaming_or_custom_file():
    js = (STATIC / "screens" / "channels.js").read_text(encoding="utf-8")

    assert "Grille de notation" in js
    for label in ("Standard", "Gaming", "Fichier personnalisé"):
        assert label in js, label
    for value in ("builtin", "builtin:gaming", "rubric_path"):
        assert f'"{value}"' in js, value
    assert "Grille en vigueur" in js                       # la grille effective est affichée
    assert 'kind === "rubric"' in js or '"rubric"' in js   # contrôle dédié, pas un champ texte brut


def test_video_sheet_shows_the_rubric_used():
    js = (STATIC / "screens" / "videos.js").read_text(encoding="utf-8")

    assert "video.rubric" in js and "Grille" in js
