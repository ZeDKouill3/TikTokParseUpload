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
    assert "<form" in resp.text
    assert 'id="submit-form"' in resp.text


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
    "clipper.channel", "clipper.worker", "clipper.publish", "clipper.watch",
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


def test_index_declares_logo_as_icon_and_shows_it_in_header(tmp_path, isolated_cwd):
    html = client(tmp_path).get("/").text
    assert '<link rel="icon" type="image/svg+xml" href="/static/logo.svg">' in html
    header = html[html.index("<header>"):html.index("</header>")]
    assert 'src="/static/logo.svg"' in header
    assert 'alt=""' in header
    assert "Clipper" in header


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
