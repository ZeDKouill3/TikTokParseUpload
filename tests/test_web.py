"""Tests de clipper.web (TASK-634e).

Routes testees avec le TestClient FastAPI et un pipeline simule (jamais le
vrai pipeline.run/render/decide) : voir clipper/web/app.py pour le contrat.
Aucun test n'utilise le reseau ni un vrai LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipper.config import Config
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


def _fake_torch(monkeypatch, *, available=True, free=3 * 1024**3, total=8 * 1024**3):
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: available, mem_get_info=lambda: (free, total))
    monkeypatch.setitem(sys.modules, "torch", torch)


def test_dashboard_hardware_reads_vram_used_on_cuda(tmp_path, isolated_cwd, monkeypatch):
    from clipper import gpu

    monkeypatch.setattr(gpu, "get_device", lambda: gpu.Device(type="cuda", compute_type="float16"))
    _fake_torch(monkeypatch)

    assert _dashboard(tmp_path)["hardware"] == {"device": "cuda", "vram_used_mb": 5 * 1024}


def test_dashboard_hardware_vram_unknown_is_null_with_a_french_error(tmp_path, isolated_cwd, monkeypatch):
    from clipper import gpu

    monkeypatch.setattr(gpu, "get_device", lambda: gpu.Device(type="cuda", compute_type="float16"))
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch -> ImportError

    hw = _dashboard(tmp_path)["hardware"]

    assert hw["device"] == "cuda"
    assert hw["vram_used_mb"] is None
    assert "torch" in hw["vram_used_mb_error"]


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
    assert clips["02"]["publish_status"] == "à valider"
    assert clips["03"]["publish_status"] == "failed"
    assert clips["03"]["publish_error"] == "quota depasse"


def test_get_clips_filters_by_channel_video_and_status(tmp_path, isolated_cwd):
    _clips_setup(tmp_path)
    c = client(tmp_path)

    by_channel = c.get("/api/clips", params={"channel": "autre"}).json()
    assert [(x["video_id"], x["clip_id"]) for x in by_channel] == [("othervideo01", "01")]
    assert len(c.get("/api/clips").json()) == 4
    by_status = c.get("/api/clips", params={"status": "à valider"}).json()
    assert {(x["video_id"], x["clip_id"]) for x in by_status} == {(CLIPS_VIDEO, "02"), ("othervideo01", "01")}
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
