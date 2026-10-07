"""Veille (4/4) : routes /api/veille, clips archives, reglages et ecran (SPEC-bdd9 R8-R10, ADR-ca9a).

Le serveur web n'appelle jamais de collecteur ni de LLM (ADR-09ad) : il lit
state/veille/ et depose des demandes. Etat sous tmp_path, aucun reseau.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
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


def test_get_veille_exposes_the_three_igdb_settings(tmp_path, isolated_cwd):
    data = client(tmp_path, enabled=True, upcoming_days=9, release_window_days=4, igdb_min_hypes=7).get("/api/veille").json()
    assert (data["settings"]["upcoming_days"], data["settings"]["release_window_days"],
            data["settings"]["igdb_min_hypes"]) == (9, 4, 7)


def test_put_settings_writes_the_igdb_settings(tmp_path, isolated_cwd):
    write_config(tmp_path, SETTINGS_TOML)
    resp = sclient(tmp_path).put("/api/settings", json={"settings": {"veille": {
        "upcoming_days": 21, "release_window_days": 0, "igdb_min_hypes": 12}}})
    assert resp.status_code == 200, resp.text
    table = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))["veille"]
    assert (table["upcoming_days"], table["release_window_days"], table["igdb_min_hypes"]) == (21, 0, 12)


@pytest.mark.parametrize("key,value,message", [
    ("upcoming_days", 0, "[veille] upcoming_days doit être un entier >= 1 (reçu 0)"),
    ("release_window_days", -1, "[veille] release_window_days doit être un entier >= 0 (reçu -1)"),
    ("igdb_min_hypes", -5, "[veille] igdb_min_hypes doit être un entier >= 1 (reçu -5)"),
])
def test_put_settings_refuses_an_out_of_range_igdb_setting_with_the_veille_message(
        tmp_path, isolated_cwd, key, value, message):
    write_config(tmp_path, SETTINGS_TOML)
    before = (tmp_path / "config.toml").read_text(encoding="utf-8")
    resp = sclient(tmp_path).put("/api/settings", json={"settings": {"veille": {key: value}}})
    assert resp.status_code == 400
    assert message in resp.json()["detail"]
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == before


RELEASES = {
    "recent": [{"igdb_id": "1", "name": "Jeu Sorti", "key": "jeu sorti", "slug": "jeu-sorti",
                "url": "https://www.igdb.com/games/jeu-sorti", "hypes": 40, "date": "2026-10-04", "human": "4 Oct",
                "platforms": ["PC"], "regions": [], "statuses": [], "days": -3}],
    "upcoming": [{"igdb_id": "2", "name": "Jeu A Venir", "key": "jeu a venir", "slug": "jeu-a-venir",
                  "url": "https://www.igdb.com/games/jeu-a-venir", "hypes": None, "date": "2026-10-12",
                  "human": "12 Oct", "platforms": ["PC", "PS5"], "regions": [], "statuses": [], "days": 5}],
    "excluded_low_hypes": 3, "truncated": {"recent": 2, "upcoming": 0},
}


def test_get_veille_returns_releases_and_igdb_source_as_written(tmp_path, isolated_cwd):
    state = day_state(today())
    state["releases"] = RELEASES
    state["sources"]["igdb"] = {"status": "error", "at": f"{today()}T05:00:00+00:00", "error": "IGDB 401", "counts": {}}
    write_json(tmp_path / "state" / "veille" / "days" / f"{today()}.json", state)
    write_json(tmp_path / "state" / "veille" / "days" / f"{yesterday()}.json", state)
    c = client(tmp_path, enabled=True)
    for data in (c.get("/api/veille").json(), c.get(f"/api/veille/{yesterday()}").json()):
        assert data["day"]["releases"] == RELEASES
        assert data["day"]["sources"]["igdb"]["error"] == "IGDB 401"


def test_veille_screen_has_the_releases_section_between_proposals_and_best_clips():
    js = read_static("screens/veille.js")
    for needle in ("Sorties de jeux", "Sorties récentes", "À venir (", "Aucune sortie dans la fenêtre", "autres",
                   "data-veille-releases", "IGDB (sorties)", "igdb:", "excluded_low_hypes"):
        assert needle in js, needle
    view = js[js.index("function veilleView"):]
    assert view.index("veilleProposals(data") < view.index("veilleReleases(data") < view.index("veilleBest(data")


def test_veille_screen_shows_release_badges_on_proposals_and_rising_rows():
    js = read_static("screens/veille.js")
    assert "release_days_since" in js[js.index("function veilleProposal"):js.index("function veilleProposals")]
    assert "Sortie J+" in js
    assert "g.release" in js[js.index("function veilleRising"):js.index("function veilleSettings")]
    assert "upcoming_days" in js[js.index("function veilleSettings"):]


def test_settings_screen_edits_the_three_igdb_settings():
    js = read_static("screens/settings.js")
    shown = js[js.index("function setVeille()"):].split("\n")[1]
    assert shown.lstrip().startswith("const shown")  # les champs montrés d'emblée, pas « autres réglages »
    for key in ("upcoming_days", "release_window_days", "igdb_min_hypes"):
        assert key in shown, key


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


def test_veille_screen_shows_sellers_rank_and_french_count_labels():
    js = read_static("screens/veille.js")
    for needle in ("Ventes FR", "steam_sellers_rank", "steam_sellers_gain", "steam_sellers_new",
                   "Nouveau dans le top ventes FR", "steam_fr:", "COUNT_LABELS", "jeux"):
        assert needle in js, needle
    assert "${v} ${k}" not in js  # « Steam : 99 games » : les clés d'API ne s'affichent plus telles quelles


def test_veille_rising_indicator_counts_rank_gains_not_only_seven_day_rise():
    js = read_static("screens/veille.js")
    rises = js[js.index("const veilleRises"):js.index("function veilleSellers")]
    for needle in ("steam_rank_gain", "steam_new_in_top", "steam_sellers_gain", "steam_sellers_new"):
        assert needle in rises, needle
    assert "steam_rank_gain_min" in js[js.index("function veilleKpis"):js.index("function veilleProposal")]


# --- TASK-a898 : miniatures, VOD réservées, libellé Steam -------------------


def test_veille_proposal_card_shows_the_thumbnail_lazily_and_keeps_the_grey_block():
    js = read_static("screens/veille.js")
    card = js[js.index("function veilleProposal"):]
    assert "c.thumbnail_url" in card and 'loading="lazy"' in card.split("c.thumbnail_url")[1].split("</div>")[0]
    assert '<div class="art">' in card  # le bloc gris reste le fond (miniature absente ou en échec)


def test_veille_hors_steam_only_when_absent_from_every_steam_source():
    js = read_static("screens/veille.js")
    delta = js[js.index("function veilleDelta"):js.index("function veilleSellers")]
    assert 'kind === "steam" && !game.steam_match' in delta and "steam_sellers_rank" in delta
    cell = js[js.index("function veilleSteamCell"):js.index("const COMMUNITY_LABELS")]
    assert "steam_sellers_rank" in cell and "hors Steam" in cell


def test_veille_source_detail_labels_the_private_vod_counter():
    js = read_static("screens/veille.js")
    assert "private:" in js[js.index("const COUNT_LABELS"):].split("\n")[0]
    assert "réservées" in js


def test_veille_js_is_syntactically_valid():
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent du PATH")
    done = subprocess.run([node, "--check", str(STATIC / "screens" / "veille.js")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_veille_source_detail_labels_the_restricted_vod_counter():
    js = (STATIC / "screens" / "veille.js").read_text(encoding="utf-8")
    assert "restricted:" in js[js.index("const COUNT_LABELS"):].split("\n")[0]


def test_veille_card_shows_the_unverified_access_reason():
    js = (STATIC / "screens" / "veille.js").read_text(encoding="utf-8")
    assert "access_unverified" in js[js.index("function veilleProposal"):]


# --- TASK-4944 : calendrier des sorties (SPEC-df51 R17) ---------------------
#
# Les fonctions de veille.js tournent pour de vrai sous node (vm, esc/fr/icon factices) : on lit le HTML qu'elles
# rendent, pas leur code source.

NODE_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const [src, input] = process.argv.slice(2);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ctx = { console, document: { addEventListener() {} }, esc, CLIPPER_TZ: "Europe/Paris", Screens: {}, store: {},
  fr: (n, d) => Number(n).toLocaleString("fr-FR", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }),
  icon: (name) => `<svg data-icon="${name}"></svg>`, currentScreen: "veille", renderCurrent() {}, updateCounts() {},
  api: async () => ({}), emptyState: (i, t) => `<div>${t}</div>` };
vm.createContext(ctx);
const jobs = JSON.parse(fs.readFileSync(input, "utf8"));
const run = vm.runInContext(fs.readFileSync(src, "utf8") + "\n;(function (jobs) { return jobs.map(([fn, ...args]) => { if (fn === 'ui') { Object.assign(veilleUi, args[0]); return null; } return ({ veilleReleases, veilleSources, veilleKpis, veilleRising, veilleSettings })[fn](...args); }); })", ctx);
process.stdout.write(JSON.stringify(run(jobs)));
"""


def run_js(tmp_path, *jobs):
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent du PATH")
    (tmp_path / "harness.js").write_text(NODE_HARNESS, encoding="utf-8")
    (tmp_path / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    done = subprocess.run([node, str(tmp_path / "harness.js"), str(STATIC / "screens" / "veille.js"),
                           str(tmp_path / "jobs.json")], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return [flat(html) if isinstance(html, str) else html for html in json.loads(done.stdout)]


def flat(text: str) -> str:
    """Le texte que l'utilisateur lit : entités HTML décodées, espaces fines / insécables ramenées à une espace."""
    return html_lib.unescape(text).replace(chr(0x202F), " ").replace(chr(0xA0), " ")


def cards(html):
    """Les cartes du bandeau « Sorties récentes », dans l'ordre."""
    band = html[html.index('class="recent"'):html.index('class="cal-frise"')]
    return re.split(r'(?=<article class="rc">)', band)[1:]


def entry(igdb_id, name, days, *, hypes=40, cover="co1abc", platforms=("PC",), portage=False, trend=None, url=True):
    when = (datetime(2026, 10, 7) + timedelta(days=days)).date().isoformat()
    slug = name.lower().replace(" ", "-")
    return {"igdb_id": igdb_id, "name": name, "key": name.lower(), "slug": slug,
            "url": f"https://www.igdb.com/games/{slug}" if url else None, "hypes": hypes,
            "cover_image_id": cover, "steam_appid": None, "first_release_date": None, "date": when, "human": when,
            "days": days, "platforms": list(platforms), "regions": [], "statuses": [], "portage": portage, "trend": trend}


TREND = {"key": "jeu", "name": "Jeu", "twitch_fr_viewers": 502, "twitch_delta_pct": None, "steam_players": None,
         "steam_rank": None, "steam_rank_gain": None, "steam_new_in_top": None, "steam_sellers_rank": 2,
         "steam_sellers_gain": 122, "steam_sellers_new": False, "steam_players_now": 1840, "steam_followers": 15200,
         "steam_followers_gain_7d": 310,
         "community": {"ok": True, "steam_players": 1840, "steam_kind": "now", "steam_followers": 15200,
                       "twitch_fr_viewers": 502, "hypes": 40, "met": ["followers", "twitch"]},
         "steam_players_history": [{"date": "2026-10-06", "kind": "peak", "players": 900},
                                   {"date": "2026-10-06", "kind": "now", "players": 700},
                                   {"date": "2026-10-07", "kind": "now", "players": 1840}]}

CFG = {"upcoming_days": 14, "release_window_days": 15, "igdb_min_hypes": 5, "run_at": "07:00", "taste": ""}


def cal_data(recent=(), upcoming=(), *, excluded=0, truncated=(0, 0), igdb=None, cfg=None):
    sources = {"igdb": igdb or {"status": "ok", "at": "x", "error": None, "counts": {}}}
    return {"enabled": True, "running": False, "settings": {**CFG, **(cfg or {})},
            "day": {"date": "2026-10-07", "sources": sources, "proposals": [], "games": [],
                    "releases": {"recent": list(recent), "upcoming": list(upcoming), "excluded_low_hypes": excluded,
                                 "truncated": {"recent": truncated[0], "upcoming": truncated[1]}}}}


def calendar(tmp_path, data, sheet=None):
    return run_js(tmp_path, ["ui", {"sheet": sheet}], ["veilleReleases", data])[1]


def test_get_veille_exposes_and_put_writes_every_calendar_and_community_setting(tmp_path, isolated_cwd):
    keys = {"upcoming_days": 10, "release_window_days": 3, "igdb_min_hypes": 2, "igdb_recent_max": 6,
            "igdb_upcoming_max": 8, "steam_players_lookups_max": 11, "steam_followers_lookups_max": 12,
            "steam_followers_pause_s": 0.5, "community_min_steam_players": 13, "community_min_steam_followers": 14,
            "community_min_twitch_viewers": 15, "community_min_hypes": 16, "max_vods_per_game": 2}
    assert client(tmp_path, enabled=True, **keys).get("/api/veille").json()["settings"].items() >= keys.items()
    write_config(tmp_path, SETTINGS_TOML)
    resp = sclient(tmp_path).put("/api/settings", json={"settings": {"veille": keys}})
    assert resp.status_code == 200, resp.text
    table = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))["veille"]
    assert {k: table[k] for k in keys} == keys


@pytest.mark.parametrize("key,value,message", [
    ("igdb_recent_max", 0, "[veille] igdb_recent_max doit être un entier >= 1 (reçu 0)"),
    ("igdb_upcoming_max", 0, "[veille] igdb_upcoming_max doit être un entier >= 1 (reçu 0)"),
    ("max_vods_per_game", 0, "[veille] max_vods_per_game doit être un entier >= 1 (reçu 0)"),
    ("community_min_hypes", -1, "[veille] community_min_hypes doit être un entier >= 0 (reçu -1)"),
])
def test_put_settings_refuses_out_of_range_calendar_settings_with_the_veille_message(
        tmp_path, isolated_cwd, key, value, message):
    write_config(tmp_path, SETTINGS_TOML)
    resp = sclient(tmp_path).put("/api/settings", json={"settings": {"veille": {key: value}}})
    assert resp.status_code == 400 and message in resp.json()["detail"]


def test_get_veille_returns_the_enriched_releases_exactly_as_written(tmp_path, isolated_cwd):
    state = day_state(today())
    state["releases"] = {"recent": [entry("1", "Jeu", 0, trend=TREND)], "upcoming": [], "excluded_low_hypes": 0,
                         "truncated": {"recent": 0, "upcoming": 0}}
    state["excluded"]["no_community"] = 4
    state["sources"]["steam_players"] = {"status": "ok", "at": "x", "error": None, "counts": {"requested": 3}}
    write_json(tmp_path / "state" / "veille" / "days" / f"{today()}.json", state)
    data = client(tmp_path, enabled=True).get("/api/veille").json()
    assert data["day"]["releases"] == state["releases"] and data["day"]["excluded"]["no_community"] == 4
    assert data["day"]["sources"]["steam_players"]["counts"] == {"requested": 3}


def test_calendar_header_and_chips(tmp_path):
    html = calendar(tmp_path, cal_data([entry("1", "Sorti", -2)], [entry("2", "Bientot", 3), entry("3", "Plus tard", 5)]))
    assert "Calendrier du mercredi 7 octobre 2026" in html
    assert "1 récentes" in html and "2 à venir" in html and "Source : IGDB" in html
    assert html.index("Sorties de jeux") < html.index("Calendrier du") < html.index("Sorties récentes")


def test_recent_band_cards_follow_the_order_of_recent_with_cover_and_badges(tmp_path):
    recent = [entry("1", "Premier", 0, cover="co64f", platforms=("PC", "PS5", "XSX", "NS2", "Mac"), portage=True,
                    hypes=1234, trend=TREND),
              entry("2", "Second", -4, cover="coaarl", hypes=90)]
    html = calendar(tmp_path, cal_data(recent))
    band = html[html.index("Sorties récentes"):html.index("À venir (")]
    assert band.index("Premier") < band.index("Second")
    assert 'src="https://images.igdb.com/igdb/image/upload/t_cover_big/co64f.jpg"' in band
    assert 'alt="Jaquette de Premier"' in band and 'alt="Jaquette de Second"' in band
    first, second = cards(html)
    assert "Aujourd'hui" in first and "Sortie J+4" in second
    assert "Tendance" in first and "Tendance" not in second
    assert "PC" in first and "PS5" in first and "XSX" in first and "NS2" not in first and "+2" in first
    assert "Portage" in first and "Portage" not in second
    assert "1 234 hypes" in first and "90 hypes" in second


def test_recent_card_trend_line_uses_only_the_known_trend_fields(tmp_path):
    full = {**TREND, "steam_players": 3000}
    only_now = {**TREND, "steam_players": None, "steam_followers_gain_7d": None, "steam_sellers_rank": None,
                "steam_sellers_gain": None, "twitch_fr_viewers": None}
    html = calendar(tmp_path, cal_data([entry("1", "Complet", 0, trend=full), entry("2", "Instant", -1, trend=only_now)]))
    one, two = cards(html)
    for needle in ("ventes Steam FR", "502 viewers Twitch FR", "3 000 joueurs Steam", "pic du jour", "15 200 abonnés Steam",
                   "(+310 en 7 j)"):
        assert needle in one, needle
    assert "à l'instant du relevé" not in one
    assert "1 840 joueurs Steam" in two and "à l'instant du relevé" in two and "pic du jour" not in two
    assert "15 200 abonnés Steam" in two and "en 7 j" not in two and "viewers Twitch" not in two
    assert "ventes Steam" not in two


def test_recent_card_community_chip_or_peu_de_monde(tmp_path):
    quiet = {**TREND, "community": {"ok": False, "met": []}}
    html = calendar(tmp_path, cal_data([entry("1", "Animee", 0, trend=TREND), entry("2", "Calme", -1, trend=quiet),
                                        entry("3", "Sans", -2)]))
    one, two, three = cards(html)
    assert "Communauté" in one and "Peu de monde" not in one
    assert "Peu de monde" in two and "Communauté" not in two
    assert "Peu de monde" not in three and "Communauté" not in three and "Tendance" not in three


def test_cover_without_image_id_is_a_name_thumbnail_and_uses_no_other_address(tmp_path):
    html = calendar(tmp_path, cal_data([entry("1", "Sans Jaquette", 0, cover=None)]))
    card = cards(html)[0]
    assert "<img" not in card and "Sans Jaquette" in card and "cover err" in card
    assert "http" not in card
    html = calendar(tmp_path, cal_data([entry("1", "Avec", 0, cover="co1")]))
    assert "classList.add('err')" in html  # image en erreur : la vignette porte le nom
    assert set(re.findall(r'src="(https?://[^"]+)"', html)) == {"https://images.igdb.com/igdb/image/upload/t_cover_big/co1.jpg"}


def columns(html):
    """Les colonnes de la frise, dans l'ordre."""
    frise = html[html.index('class="cal-frise"'):html.index('class="mlist"')]
    return re.split(r'(?=<div class="day[ "])', frise)[1:]


def test_frise_has_one_column_per_day_with_today_marked_and_filled_from_recent(tmp_path):
    recent = [entry("1", "Aujourdhui", 0), entry("9", "Hier", -1)]
    upcoming = [entry("2", "Petit", 1, hypes=3), entry("3", "Grand", 1, hypes=500), entry("4", "Loin", 14)]
    html = calendar(tmp_path, cal_data(recent, upcoming))
    assert "À venir (14 j)" in html
    cols = columns(html)
    assert len(cols) == 15
    assert "day today" in cols[0] and "Aujourdhui" in cols[0] and not any("day today" in c for c in cols[1:])
    assert "Hier" not in "".join(cols)
    # ordre du tableau (aucun tri par hypes dans le JS) : « Petit » avant « Grand », le premier en grand
    assert cols[1].index("Petit") < cols[1].index("Grand") and cols[1].index("pick big") < cols[1].index("Petit")
    assert "Aucune sortie notable" in cols[2] and "Loin" in cols[14]


def test_frise_first_cover_shows_hypes_five_at_most_then_plus_n_autres(tmp_path):
    upcoming = [entry(str(i), f"Jeu{i}", 2, hypes=100 - i) for i in range(8)]
    col = columns(calendar(tmp_path, cal_data([], upcoming)))[2]
    assert col.count("data-veille-open") == 5 and "+3 autres" in col and "100 hypes" in col
    assert "Jeu5" not in col and "Jeu4" in col


def test_frise_follows_the_upcoming_days_setting(tmp_path):
    html = calendar(tmp_path, cal_data([], [entry("1", "X", 2)], cfg={"upcoming_days": 5}))
    assert "À venir (5 j)" in html and len(columns(html)) == 6


def test_phone_list_shows_only_days_with_releases_and_counts_the_empty_ones_between(tmp_path):
    upcoming = [entry("1", "Aaa", 1), entry("2", "Bbb", 4), entry("3", "Ccc", 5), entry("4", "Ddd", 6)]
    html = calendar(tmp_path, cal_data([], upcoming))
    mlist = html[html.index('class="mlist"'):]
    assert len(re.findall(r'class="mday[ "]', mlist)) == 4
    assert "2 jours sans sortie notable" in mlist and mlist.count("sans sortie notable") == 1
    assert mlist.index("Aaa") < mlist.index("2 jours sans") < mlist.index("Bbb") < mlist.index("Ddd")


def test_phone_layout_hides_the_frise_by_css():
    css = read_static("screens/veille.css")
    media = css[css.index("@media (max-width: 760px)"):]
    assert re.search(r"\.cal-frise[^{]*\{[^}]*display:\s*none", media)
    assert re.search(r"\.mlist\s*\{[^}]*display:\s*block", media)
    assert re.search(r"\.mlist\s*\{[^}]*display:\s*none", css[:css.index("@media (max-width: 760px)")])


def test_detail_sheet_opens_on_a_cover_and_shows_everything(tmp_path):
    release = entry("1", "Detail", -3, platforms=("PC", "PS5", "XSX", "NS2", "Mac"), portage=True, trend=TREND, hypes=77)
    html = calendar(tmp_path, cal_data([release]), sheet="1")
    assert 'role="dialog"' in html and 'aria-modal="true"' in html and "data-veille-close" in html
    sheet = html[html.index('role="dialog"'):]
    assert 'alt="Jaquette de Detail"' in sheet and "dimanche 4 octobre 2026" in sheet and "Sortie J+3" in sheet
    for platform in ("PC", "PS5", "XSX", "NS2", "Mac"):
        assert platform in sheet
    assert "77" in sheet and "Portage sur nouvelle plateforme" in sheet and "502 viewers Twitch FR" in sheet
    assert 'href="https://www.igdb.com/games/detail"' in sheet and 'target="_blank"' in sheet and "Voir sur IGDB" in sheet
    assert "data-veille-spark" in sheet  # la courbe des joueurs
    assert "Chercher des VOD" not in sheet


def test_detail_sheet_day_chips_and_absence_of_optional_blocks(tmp_path):
    data = cal_data([entry("1", "Jour", 0)], [entry("2", "Futur", 5, hypes=10)])
    sheet = calendar(tmp_path, data, sheet="2")
    sheet = sheet[sheet.index('role="dialog"'):]
    assert "J-5" in sheet and "Portage" not in sheet and "Tendance" not in sheet and "data-veille-spark" not in sheet
    today_sheet = calendar(tmp_path, data, sheet="1")
    assert "Aujourd'hui" in today_sheet[today_sheet.index('role="dialog"'):]
    assert 'role="dialog"' not in calendar(tmp_path, data, sheet=None)


def test_detail_sheet_wiring_closes_on_button_escape_and_outside_click():
    js = read_static("screens/veille.js")
    wire = js[js.index("function veilleWire"):]
    for needle in ("data-veille-open", "data-veille-close", '"Escape"', "veilleUi.sheet = null", "e.target === "):
        assert needle in wire, needle
    assert "Chercher des VOD" not in js


def test_calendar_states_truncated_excluded_empty_and_error(tmp_path):
    html = calendar(tmp_path, cal_data([entry("1", "A", 0)], [entry("2", "B", 2)], excluded=3, truncated=(4, 2)))
    assert "+4 autres" in html and "+2 autres" in html and "3 sorties écartées (moins de 5 hypes)" in html
    html = calendar(tmp_path, cal_data(excluded=1))
    assert "Aucune sortie dans la fenêtre" in html and "1 sortie écartée (moins de 5 hypes)" in html
    assert "autres" not in html
    error = {"status": "error", "at": "x", "error": "IGDB 401", "counts": {}}
    html = calendar(tmp_path, cal_data([entry("1", "Cache", 0)], igdb=error))
    assert "IGDB 401" in html and 'role="alert"' in html and "Cache" not in html and "Calendrier du" not in html


def test_sources_strip_names_the_two_steam_lookup_sources(tmp_path):
    sources = {"igdb": {"status": "ok", "at": "x", "error": None, "counts": {"recent": 2}},
               "steam_players": {"status": "ok", "at": "x", "error": None, "counts": {"requested": 3, "found": 2}},
               "steam_followers": {"status": "error", "at": "x", "error": "memberslistxml 500", "counts": {}}}
    data = cal_data()
    data["day"].update(sources=sources, llm={"status": "ok"}, finished_at="2026-10-07T05:00:00+00:00")
    html = run_js(tmp_path, ["veilleSources", data])[0]
    assert "IGDB (sorties)" in html and "Steam (joueurs hors top)" in html and "Steam (abonnés)" in html
    assert "memberslistxml 500" in html


GAME = {"key": "jeu", "name": "Jeu", "twitch_match": True, "twitch_fr_viewers": 300, "twitch_delta_pct": 10,
        "steam_match": False, "steam_players": None, "steam_players_now": 2500, "steam_delta_pct": None,
        "steam_now_delta_pct": 25.0, "steam_followers": 42000, "steam_followers_gain_7d": 1200, "vod_count": 4,
        "steam_sellers_rank": None, "baseline_days_available": 2,
        "community": {"ok": True, "met": ["steam", "twitch"]},
        "steam_players_history": [{"date": "2026-10-06", "kind": "peak", "players": 2000},
                                  {"date": "2026-10-06", "kind": "now", "players": 1900},
                                  {"date": "2026-10-07", "kind": "now", "players": 2500}]}


def rising(tmp_path, *games):
    data = cal_data()
    data["day"]["games"] = list(games)
    return run_js(tmp_path, ["veilleRising", data])[0]


def test_rising_table_has_the_community_followers_and_steam_columns(tmp_path):
    html = rising(tmp_path, GAME)
    for header in ("Communauté", "Abonnés Steam", "Steam (pic du jour / à l'instant)"):
        assert f">{header}<" in html, header
    assert "2 500 à l'instant" in html and "+25" in html and "(à l'instant)" in html
    assert "42 000" in html and "+1 200 (7 j)" in html
    assert '<b class="ok">ok</b>' in html


def test_rising_row_explains_missing_followers_and_community(tmp_path):
    bare = {**GAME, "steam_players_now": None, "steam_now_delta_pct": None, "steam_followers": None,
            "steam_followers_gain_7d": None, "community": {"ok": False, "met": []}, "steam_players_history": []}
    html = rising(tmp_path, bare)
    assert "inconnu" in html and "historique insuffisant" in html and "insuffisante" in html
    peak = rising(tmp_path, {**GAME, "steam_match": True, "steam_players": 3100, "steam_delta_pct": 40})
    assert "3 100" in peak and "3 100 à l'instant" not in peak and "+40" in peak and "(à l'instant)" not in peak


def test_rising_sparkline_draws_peak_and_now_points_in_distinct_colors(tmp_path):
    html = rising(tmp_path, GAME)
    start = html.index("data-veille-spark")
    svg = html[html.index("<svg", start):html.index("</svg>", start)]
    assert svg.count("<circle") == 3 and "<polyline" in svg
    assert len(re.findall(r'<circle[^>]*class="[^"]*\bpk\b', svg)) == 1
    assert len(re.findall(r'<circle[^>]*class="[^"]*\bnw\b', svg)) == 2
    css = read_static("screens/veille.css")
    peak = re.search(r"\.pk\b[^{]*\{([^}]*)\}", css).group(1)
    now = re.search(r"\.nw\b[^{]*\{([^}]*)\}", css).group(1)
    assert "fill" in peak and "fill" in now and peak != now


def test_rising_sparkline_with_fewer_than_two_points_says_one_day_of_measure(tmp_path):
    one = {**GAME, "steam_players_history": [{"date": "2026-10-07", "kind": "now", "players": 2500}]}
    html = rising(tmp_path, one)
    assert "1 jour de mesure" in html and "data-veille-spark" not in html


def test_kpi_shows_the_no_community_exclusions_only_when_known(tmp_path):
    data = cal_data()
    data["day"].update(proposals=[], excluded={"already_known": 1, "too_short": 2, "no_community": 6})
    assert "6 VOD écartées : communauté insuffisante ou jeu inconnu" in run_js(tmp_path, ["veilleKpis", data])[0]
    data["day"]["excluded"] = {"already_known": 1, "too_short": 2}
    assert "communauté insuffisante" not in run_js(tmp_path, ["veilleKpis", data])[0]


def test_settings_preview_shows_every_new_setting(tmp_path):
    keys = ["igdb_recent_max", "igdb_upcoming_max", "steam_players_lookups_max", "steam_followers_lookups_max",
            "steam_followers_pause_s", "community_min_steam_players", "community_min_steam_followers",
            "community_min_twitch_viewers", "community_min_hypes", "max_vods_per_game"]
    data = cal_data(cfg={k: 100 + i for i, k in enumerate(keys)})
    html = run_js(tmp_path, ["veilleSettings", data])[0]
    for i, key in enumerate(keys):
        assert f'data-veille-setting="{key}"' in html and f'value="{100 + i}"' in html, key


def test_settings_screen_edits_every_calendar_community_and_diversity_setting():
    js = read_static("screens/settings.js")
    shown = js[js.index("function setVeille()"):].split("\n")[1]
    for key in ("igdb_recent_max", "igdb_upcoming_max", "steam_players_lookups_max", "steam_followers_lookups_max",
                "steam_followers_pause_s", "community_min_steam_players", "community_min_steam_followers",
                "community_min_twitch_viewers", "community_min_hypes", "max_vods_per_game",
                "upcoming_days", "release_window_days", "igdb_min_hypes", "run_at"):
        assert key in shown, key


def test_the_web_server_never_fetches_stores_or_relays_an_igdb_image():
    for path in (Path(__file__).resolve().parent.parent / "clipper" / "web").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "images.igdb.com" not in text and "cover_image_id" not in text, path.name
    app = create_app(config=Config(mode="review", workspace_dir=Path("w"), output_dir=Path("o")))
    routes = {getattr(r, "path", "") for r in app.routes}
    assert not any(word in route for route in routes if "veille" in route for word in ("cover", "igdb", "image"))
    assert read_static("screens/veille.js").count("https://images.igdb.com/igdb/image/upload/") == 1  # une seule adresse, lue par le navigateur
