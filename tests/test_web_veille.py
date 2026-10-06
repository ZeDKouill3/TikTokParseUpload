"""Veille (4/4) : routes /api/veille, clips archives, reglages et ecran (SPEC-bdd9 R8-R10, ADR-ca9a).

Le serveur web n'appelle jamais de collecteur ni de LLM (ADR-09ad) : il lit
state/veille/ et depose des demandes. Etat sous tmp_path, aucun reseau.
"""

from __future__ import annotations

import asyncio
import json
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from clipper import journal, llm, veille, veille_sources, worker
from clipper.config import Config, load_config
from clipper.web import create_app

STATIC = Path(__file__).resolve().parent.parent / "clipper" / "web" / "static"
PARIS = ZoneInfo("Europe/Paris")
SENTINEL_SECRET = "sentinelle-secret-9f3a"
SENTINEL_KEY = "sentinelle-cle-api-71bc"


def today() -> str:
    return datetime.now(PARIS).date().isoformat()


def yesterday() -> str:
    return (datetime.now(PARIS).date() - timedelta(days=1)).isoformat()


def make_config(tmp_path, **veille_table) -> Config:
    sections = {"veille": veille_table} if veille_table else {}
    return Config(mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
                  _sections=sections)


def client(tmp_path, **veille_table) -> TestClient:
    return TestClient(create_app(config=make_config(tmp_path, **veille_table)))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def candidate(video_id="v1", **extra):
    return {"id": f"twitch:{video_id}", "source": "twitch", "video_id": video_id,
            "url": f"https://www.twitch.tv/videos/{video_id}", "title": "Titre", "channel_name": "streamer_a",
            "game_key": "jeu a", "game_name": "Jeu A", "duration_s": 7200, "published_at": "2026-10-05T20:00:00+00:00",
            "view_count": 1200, "views_per_hour": None, "signals": {"twitch_delta_pct": 80, "steam_delta_pct": None},
            **extra}


def proposal(video_id="v1", status="proposed", rank=1):
    return {"candidate_id": f"twitch:{video_id}", "rank": rank, "reason": "Ça monte", "status": status,
            "decided_at": None, "channel": None, "queue_entry_id": None, "candidate": candidate(video_id)}


def day_state(date, *, finished=True, proposals=None, sources=None):
    return {
        "date": date, "started_at": f"{date}T05:00:00+00:00",
        "finished_at": f"{date}T05:01:00+00:00" if finished else None,
        "sources": sources or {s: {"status": "ok", "at": f"{date}T05:00:00+00:00", "error": None, "counts": {}}
                               for s in veille.SOURCES},
        "games": [], "candidates": [candidate()], "excluded": {"too_short": 0, "too_old": 0, "already_known": 0},
        "llm": {"status": "ok", "error": None, "model": "strong"},
        "proposals": [proposal()] if proposals is None else proposals, "skipped_note": "", "refresh_requested_at": None,
    }


def put_day(tmp_path, date, **kwargs):
    write_json(tmp_path / "state" / "veille" / "days" / f"{date}.json", day_state(date, **kwargs))


# --------------------------------------------------------------------------
# (1) GET /api/veille
# --------------------------------------------------------------------------


def test_get_veille_without_any_state_says_so_and_never_leaks_keys(tmp_path, isolated_cwd):
    data = client(tmp_path, enabled=True).get("/api/veille").json()
    assert data["day"] is None and data["selection"] is None
    assert data["enabled"] is True and data["running"] is False
    assert data["twitch_client_id_set"] is False and data["youtube_api_key_set"] is False


def test_get_veille_returns_todays_state_with_selection_flags_and_next_run(tmp_path, isolated_cwd):
    put_day(tmp_path, today())
    write_json(tmp_path / "state" / "veille" / "selection" / f"{today()}.json",
               {"date": today(), "kept": [], "archived": [], "restored": []})
    resp = client(tmp_path, enabled=True, twitch_client_id="id-1", twitch_client_secret=SENTINEL_SECRET,
                  youtube_api_key=SENTINEL_KEY).get("/api/veille")
    data = resp.json()

    assert data["day"]["date"] == today() and data["day"]["proposals"][0]["candidate_id"] == "twitch:v1"
    assert data["selection"]["date"] == today()
    assert data["enabled"] is True and data["running"] is False
    assert data["settings"]["max_vods_per_day"] == 3 and data["settings"]["run_at"] == "07:00"
    assert "twitch_client_secret" not in data["settings"] and "youtube_api_key" not in data["settings"]
    assert data["twitch_client_id_set"] is True and data["twitch_client_secret_set"] is True
    assert data["youtube_api_key_set"] is True
    assert SENTINEL_SECRET not in resp.text and SENTINEL_KEY not in resp.text and "id-1" not in resp.text
    assert datetime.fromisoformat(data["next_run_at"]).tzinfo is not None


def test_get_veille_falls_back_to_the_last_run_when_today_has_none(tmp_path, isolated_cwd):
    put_day(tmp_path, "2026-01-02")
    put_day(tmp_path, "2026-01-03")
    data = client(tmp_path, enabled=True).get("/api/veille").json()
    assert data["day"]["date"] == "2026-01-03"


def test_get_veille_flags_running_and_disabled_has_no_next_run(tmp_path, isolated_cwd):
    put_day(tmp_path, today(), finished=False)
    assert client(tmp_path, enabled=True).get("/api/veille").json()["running"] is True
    off = client(tmp_path).get("/api/veille").json()
    assert off["enabled"] is False and off["next_run_at"] is None


def test_get_veille_keeps_source_errors_as_they_are(tmp_path, isolated_cwd):
    sources = {"twitch": {"status": "error", "at": "x", "error": "twitch_client_id absente : à saisir dans Réglages › Veille",
                          "counts": {}},
               "youtube": {"status": "ok", "at": "x", "error": None, "counts": {"videos": 3}},
               "steam": {"status": "ok", "at": "x", "error": None, "counts": {}}}
    put_day(tmp_path, today(), sources=sources)
    data = client(tmp_path, enabled=True).get("/api/veille").json()
    assert data["day"]["sources"] == sources


def test_get_veille_unreadable_state_is_a_500_naming_the_file(tmp_path, isolated_cwd):
    path = tmp_path / "state" / "veille" / "days" / f"{today()}.json"
    path.parent.mkdir(parents=True)
    path.write_text("{pas du json", encoding="utf-8")
    resp = client(tmp_path, enabled=True).get("/api/veille")
    assert resp.status_code == 500 and f"{today()}.json" in resp.json()["detail"]


def test_get_veille_by_date_and_404_when_absent(tmp_path, isolated_cwd):
    put_day(tmp_path, "2026-01-02")
    c = client(tmp_path, enabled=True)
    assert c.get("/api/veille/2026-01-02").json()["day"]["date"] == "2026-01-02"
    assert c.get("/api/veille/2026-01-09").status_code == 404
    assert c.get("/api/veille/pas-une-date").status_code == 404


# --------------------------------------------------------------------------
# (2) POST /api/veille/refresh : depose une demande, rien d'autre
# --------------------------------------------------------------------------


def test_refresh_only_writes_refresh_json_and_calls_no_collector_nor_llm(tmp_path, isolated_cwd, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("le processus web ne doit appeler ni collecteur ni LLM")

    monkeypatch.setattr(veille_sources, "default_collectors", boom)
    monkeypatch.setattr(veille, "collect", boom)
    monkeypatch.setattr(veille, "run_if_due", boom)
    monkeypatch.setattr(llm, "ask", boom)
    monkeypatch.setattr(llm, "_make_backend", boom, raising=False)

    resp = client(tmp_path, enabled=True).post("/api/veille/refresh")

    assert resp.status_code == 202
    sdir = tmp_path / "state" / "veille"
    assert "requested_at" in json.loads((sdir / "refresh.json").read_text(encoding="utf-8"))
    assert [p.name for p in sdir.rglob("*") if p.is_file()] == ["refresh.json"]


def test_refresh_is_refused_while_a_run_is_in_progress(tmp_path, isolated_cwd):
    put_day(tmp_path, today(), finished=False)
    resp = client(tmp_path, enabled=True).post("/api/veille/refresh")
    assert resp.status_code == 409
    assert not (tmp_path / "state" / "veille" / "refresh.json").exists()


def test_refresh_is_refused_when_disabled_and_says_where_to_enable(tmp_path, isolated_cwd):
    resp = client(tmp_path).post("/api/veille/refresh")
    assert resp.status_code == 409
    assert "Réglages › Veille" in resp.json()["detail"]
    assert not (tmp_path / "state" / "veille" / "refresh.json").exists()


# --------------------------------------------------------------------------
# (3) Clipper / Ignorer / Restaurer
# --------------------------------------------------------------------------


@pytest.fixture
def enqueued(monkeypatch):
    calls = []

    def fake_enqueue(url, channel, action, force_steps=None, *, short_clips=None, config=None):
        calls.append({"url": url, "channel": channel, "action": action, "short_clips": short_clips})
        return {"id": "e1", "video_id": "v1", "url": url, "channel": channel, "action": action,
                "force_steps": [], "status": "waiting"}

    monkeypatch.setattr(worker, "enqueue", fake_enqueue)
    return calls


def test_clip_queues_the_proposal_and_returns_the_queue_entry(tmp_path, isolated_cwd, enqueued):
    put_day(tmp_path, today())
    resp = client(tmp_path, enabled=True).post(
        f"/api/veille/{today()}/twitch:v1/clip", json={"channel": "ma_chaine", "short_clips": True})

    assert resp.status_code == 202
    assert resp.json()["id"] == "e1" and resp.json()["video_id"] == "v1"
    assert enqueued == [{"url": "https://www.twitch.tv/videos/v1", "channel": "ma_chaine", "action": "run",
                         "short_clips": True}]
    saved = json.loads((tmp_path / "state" / "veille" / "days" / f"{today()}.json").read_text(encoding="utf-8"))
    assert saved["proposals"][0]["status"] == "queued"


def test_clip_unknown_candidate_is_404_and_already_handled_is_409(tmp_path, isolated_cwd, enqueued):
    put_day(tmp_path, today())
    c = client(tmp_path, enabled=True)
    assert c.post(f"/api/veille/{today()}/twitch:inconnu/clip", json={}).status_code == 404
    assert c.post(f"/api/veille/{today()}/twitch:v1/clip", json={"channel": None, "short_clips": None}).status_code == 202
    assert c.post(f"/api/veille/{today()}/twitch:v1/clip", json={}).status_code == 409
    assert c.post(f"/api/veille/{today()}/twitch:v1/ignore").status_code == 409
    assert len(enqueued) == 1


def test_ignore_marks_the_proposal_ignored(tmp_path, isolated_cwd):
    put_day(tmp_path, today())
    resp = client(tmp_path, enabled=True).post(f"/api/veille/{today()}/twitch:v1/ignore")
    assert resp.status_code == 200
    saved = json.loads((tmp_path / "state" / "veille" / "days" / f"{today()}.json").read_text(encoding="utf-8"))
    assert saved["proposals"][0]["status"] == "ignored"
    seen = json.loads((tmp_path / "state" / "veille" / "seen.json").read_text(encoding="utf-8"))
    assert seen["ignored"][0]["video_id"] == "v1"


def test_restore_moves_the_clip_out_of_archived(tmp_path, isolated_cwd):
    write_json(tmp_path / "state" / "veille" / "selection" / f"{today()}.json", {
        "date": today(), "kept": [], "archived": [{"video_id": "v1", "clip_id": "c2", "score": 50, "rank": 2}],
        "restored": []})
    c = client(tmp_path, enabled=True)
    assert c.post("/api/veille/clips/v1/c2/restore").status_code == 200
    saved = json.loads((tmp_path / "state" / "veille" / "selection" / f"{today()}.json").read_text(encoding="utf-8"))
    assert saved["archived"] == [] and saved["restored"][0]["clip_id"] == "c2"
    assert c.post("/api/veille/clips/v1/c2/restore").status_code == 404


# --------------------------------------------------------------------------
# (4) /api/clips : archives masques, vue porte veille
# --------------------------------------------------------------------------


def clip_sidecar(video_id, clip_id):
    return {"video_id": video_id, "clip_id": clip_id, "part": 1, "parts_total": 1, "screen_title": "T", "title": "T",
            "caption": "D", "hashtags": [], "ready": True, "layout": "letterbox", "duration": 20.0, "score": 70.0,
            "qa": {"status": "passed", "issues": []}}


def put_clips(tmp_path):
    for clip_id in ("c1", "c2", "c3"):
        out = tmp_path / "output" / "v1"
        write_json(out / f"{clip_id}.json", clip_sidecar("v1", clip_id))
        (out / f"{clip_id}.mp4").write_bytes(b"x")
    write_json(tmp_path / "state" / "veille" / "selection" / f"{today()}.json", {
        "date": today(),
        "kept": [{"video_id": "v1", "clip_id": "c1", "score": 90, "rank": 1}],
        "archived": [{"video_id": "v1", "clip_id": "c2", "score": 50, "rank": 2}],
        "restored": [{"video_id": "v1", "clip_id": "c3", "restored_at": "2026-10-06T08:00:00+00:00"}]})


def test_clips_hides_archived_unless_asked_and_carries_the_veille_status(tmp_path, isolated_cwd):
    put_clips(tmp_path)
    c = client(tmp_path, enabled=True)
    shown = {clip["clip_id"]: clip["veille"] for clip in c.get("/api/clips").json()}
    assert shown == {"c1": {"date": today(), "status": "kept"}, "c3": {"date": today(), "status": "restored"}}
    everything = {clip["clip_id"]: clip["veille"] for clip in c.get("/api/clips?archived=1").json()}
    assert everything["c2"] == {"date": today(), "status": "archived"} and len(everything) == 3


def test_clips_outside_the_veille_have_veille_null(tmp_path, isolated_cwd):
    write_json(tmp_path / "output" / "v9" / "c1.json", clip_sidecar("v9", "c1"))
    clips = client(tmp_path).get("/api/clips").json()
    assert clips[0]["veille"] is None


# --------------------------------------------------------------------------
# (5) Reglages : cles jamais renvoyees
# --------------------------------------------------------------------------


def write_config(tmp_path, text):
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")


def sclient(tmp_path) -> TestClient:
    return TestClient(create_app(config=load_config(tmp_path / "config.toml")))


SETTINGS_TOML = f"""mode = "review"

[veille]
enabled = true
taste = "jeux coop"
twitch_client_id = "id-visible-non"
twitch_client_secret = "{SENTINEL_SECRET}"
youtube_api_key = "{SENTINEL_KEY}"
"""


def test_get_settings_has_a_veille_section_without_secret_values(tmp_path, isolated_cwd):
    write_config(tmp_path, SETTINGS_TOML)
    resp = sclient(tmp_path).get("/api/settings")
    data = resp.json()

    assert data["effective"]["veille"]["taste"] == "jeux coop" and data["effective"]["veille"]["enabled"] is True
    assert data["effective"]["veille"]["twitch_client_id_set"] is True
    assert data["effective"]["veille"]["twitch_client_secret_set"] is True
    assert data["effective"]["veille"]["youtube_api_key_set"] is True
    assert "run_at" in data["defaults"]["veille"]
    for text in (SENTINEL_SECRET, SENTINEL_KEY, "id-visible-non"):
        assert text not in resp.text


def test_put_settings_writes_the_veille_keys_when_given_and_keeps_them_otherwise(tmp_path, isolated_cwd):
    write_config(tmp_path, SETTINGS_TOML)
    c = sclient(tmp_path)

    keep = c.put("/api/settings", json={"settings": {"veille": {"enabled": False, "taste": "autre"}}})
    assert keep.status_code == 200, keep.text
    table = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))["veille"]
    assert table["enabled"] is False and table["taste"] == "autre"
    assert table["twitch_client_secret"] == SENTINEL_SECRET and table["youtube_api_key"] == SENTINEL_KEY

    new = c.put("/api/settings", json={"settings": {"veille": {"youtube_api_key": "nouvelle-cle", "run_at": "08:30"}}})
    assert new.status_code == 200, new.text
    table = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))["veille"]
    assert table["youtube_api_key"] == "nouvelle-cle" and table["run_at"] == "08:30"
    assert table["twitch_client_secret"] == SENTINEL_SECRET
    assert "nouvelle-cle" not in new.text and SENTINEL_SECRET not in new.text


def test_mask_secrets_masks_the_veille_keys():
    masked = journal.mask_secrets({"veille": {"twitch_client_secret": "s", "youtube_api_key": "k",
                                              "twitch_client_id": "i", "taste": "ok"}})
    assert masked["veille"]["twitch_client_secret"] == "***" and masked["veille"]["youtube_api_key"] == "***"
    assert masked["veille"]["taste"] == "ok"


# --------------------------------------------------------------------------
# (6) SSE
# --------------------------------------------------------------------------


def test_a_change_under_state_veille_emits_a_veille_event(tmp_path, isolated_cwd):
    from clipper.web.app import _event_stream

    config = Config(mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
                    _sections={"web": {"host": "127.0.0.1", "port": 8000, "token": "", "sse_poll_interval_s": 0.05}})

    async def run() -> dict:
        agen = _event_stream(config).__aiter__()

        async def touch() -> None:
            await asyncio.sleep(0.15)
            write_json(tmp_path / "state" / "veille" / "days" / "2026-10-06.json", {})

        asyncio.create_task(touch())
        chunk = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
        return json.loads(chunk[len("data: "):])

    event = asyncio.run(run())
    assert event["kind"] == "veille" and event["id"] == "2026-10-06"


# --------------------------------------------------------------------------
# (7) Page statique
# --------------------------------------------------------------------------


def read_static(name):
    return (STATIC / name).read_text(encoding="utf-8")


def test_navigation_has_veille_and_the_tabbar_swaps_it_for_videos():
    html = read_static("index.html")
    nav, tabbar = html.split('id="tabbar"')
    assert 'data-screen="veille"' in nav and 'data-count-for="veille"' in nav
    assert 'id="screen-veille"' in html and '/static/screens/veille.js' in html
    assert 'data-screen="veille"' in tabbar and 'data-screen="videos"' not in tabbar


def test_veille_screen_follows_the_mockup_sections():
    js = read_static("screens/veille.js")
    for needle in ("Veille désactivée", "#set-veille", "Rafraîchir", "running", "Clipper", "Ignorer", "Restaurer",
                   "Voir la VOD", "pas assez d'historique", "hors Steam", "skipped_note", "/api/veille",
                   "data-veille-sources", "data-veille-kpi", "data-veille-proposals", "data-veille-best",
                   "data-veille-rising", "data-veille-settings"):
        assert needle in js, needle


def test_veille_rising_table_marks_steam_risers_outside_twitch_fr():
    js = read_static("screens/veille.js")
    for needle in ("Nouveau dans le top Steam", "hors Twitch FR", "steam_new_in_top", "steam_rank_gain", "places"):
        assert needle in js, needle


def test_clips_screen_has_an_archived_filter():
    js = read_static("screens/clips.js")
    assert "Archivés" in js and "archived=1" in js


def test_settings_screen_has_a_veille_section_with_masked_keys():
    js = read_static("screens/settings.js")
    assert "veille" in js and "twitch_client_secret" in js and "youtube_api_key" in js
    assert "_set" in js


def test_app_counts_proposed_veille_proposals_in_the_nav():
    js = read_static("app.js")
    assert "veille" in js
