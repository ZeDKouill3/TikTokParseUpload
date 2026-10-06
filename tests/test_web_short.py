"""Clips courts dans la console (TASK-4f5e) : file, fiche video, formulaire."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipper import pipeline, worker

from test_web import URL, VIDEO_ID, client, make_config

STATIC = Path(__file__).resolve().parents[1] / "clipper" / "web" / "static"


def _spy_enqueue(monkeypatch):
    calls = []

    def fake(url, channel, action, force_steps, *, config=None, **kw):
        calls.append(kw)
        return {"id": "e1", "video_id": VIDEO_ID, "url": url, "channel": channel, "action": action,
                "force_steps": force_steps, "status": "waiting", **kw}

    monkeypatch.setattr(worker, "enqueue", fake)
    return calls


@pytest.mark.parametrize("body, expected", [({}, {}), ({"short_clips": True}, {"short_clips": True}),
                                            ({"short_clips": False}, {"short_clips": False})])
def test_queue_post_forwards_the_video_choice_only_when_given(tmp_path, isolated_cwd, monkeypatch, body, expected):
    calls = _spy_enqueue(monkeypatch)
    resp = client(tmp_path).post("/api/queue", json={"url": URL, "channel": None, "action": "run", **body})
    assert resp.status_code == 202
    assert calls == [expected]


def test_queue_post_rejects_a_non_boolean_choice(tmp_path, isolated_cwd, monkeypatch):
    _spy_enqueue(monkeypatch)
    resp = client(tmp_path).post("/api/queue", json={"url": URL, "action": "run", "short_clips": "peut-etre"})
    assert resp.status_code == 422


def test_video_sheet_shows_the_mode_written_in_moments_json(tmp_path, isolated_cwd):
    config = make_config(tmp_path)
    pipeline.save_state(pipeline.new_state(VIDEO_ID, URL, "review"), config=config)
    video_dir = Path(config.workspace_dir) / VIDEO_ID
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "moments.json").write_text(json.dumps({
        "rubric": {"path": "w/rubric-short.toml", "source": "builtin:gaming"},
        "short_clips": True, "short_min": 20, "short_max": 45, "moments": [], "rejected": [],
    }), encoding="utf-8")

    body = client(tmp_path).get(f"/api/videos/{VIDEO_ID}").json()

    assert body["short_clips"] == {"on": True, "min": 20, "max": 45}
    assert body["rubric"] == "builtin:gaming"


def test_video_sheet_without_moments_has_no_mode(tmp_path, isolated_cwd):
    config = make_config(tmp_path)
    pipeline.save_state(pipeline.new_state(VIDEO_ID, URL, "review"), config=config)
    assert client(tmp_path).get(f"/api/videos/{VIDEO_ID}").json()["short_clips"] is None


def test_add_video_form_has_a_three_state_short_clips_checkbox():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="add-short"' in app_js
    assert "short_clips" in app_js
    assert "indeterminate" in app_js  # non precise = valeur du style
