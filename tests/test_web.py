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
    assert resp.json() == state


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
    for m in re.finditer(r"""api\(\s*["`](/api[^"`?]*)[^"`]*["`]\s*(?:,\s*\{\s*method:\s*"(\w+)")?""", js):
        calls.append((m.group(2) or "GET", re.sub(r"\$\{[^}]*\}", "x", m.group(1))))
    return calls


def test_every_route_called_by_app_js_exists_in_the_app(tmp_path, isolated_cwd):
    app = create_app(config=make_config(tmp_path))
    js = "".join(p.read_text(encoding="utf-8") for p in sorted(STATIC.glob("*.js")))
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
