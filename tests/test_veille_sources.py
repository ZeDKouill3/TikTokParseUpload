"""veille_sources.py : collecteurs réels sur transport injecté (TASK-97c6, SPEC-bdd9 R3).

Un faux transport rend des réponses JSON de la forme documentée : aucun réseau.
Les tests réels (un par source) sont sautés sans ``CLIPPER_REAL_NETWORK=1``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from clipper import veille, veille_sources
from clipper.config import Config

NOW = datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc)
SECRET = "S3CR3T-client-secret"
YKEY = "Y-api-key-123"


def _settings(tmp_path, **over):
    table = dict(veille.CONFIG_DEFAULTS)
    table.update(state_dir=str(tmp_path / "state" / "veille"), twitch_client_id="cid",
                 twitch_client_secret=SECRET, youtube_api_key=YKEY, **over)
    return table


def _config(tmp_path, **over):
    return Config(mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
                  _sections={"worker": {"queue_path": str(tmp_path / "state" / "queue.json")},
                             "veille": _settings(tmp_path, **over)})


class FakeHttp:
    """Transport factice : ``routes[(method, fin de chemin)]`` = liste de réponses ou callable."""

    def __init__(self, routes):
        self.routes = {k: (list(v) if isinstance(v, list) else v) for k, v in routes.items()}
        self.calls: list[dict] = []

    def __call__(self, method, url, *, params=None, headers=None, timeout_s=20):
        path = urlparse(url).path
        self.calls.append({"method": method, "url": url, "path": path, "params": dict(params or {}),
                           "headers": dict(headers or {}), "timeout_s": timeout_s})
        for (m, suffix), reply in self.routes.items():
            if m == method and path.endswith(suffix):
                if callable(reply):
                    return reply(self.calls[-1])
                response = reply.pop(0) if len(reply) > 1 else reply[0]
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"route inattendue : {method} {url}")

    def to(self, suffix):
        return [c for c in self.calls if c["path"].endswith(suffix)]


def _token(token="tok1", expires_in=3600):
    return 200, {"access_token": token, "expires_in": expires_in, "token_type": "bearer"}


def _stream(game_id, name, viewers):
    return {"game_id": game_id, "game_name": name, "viewer_count": viewers, "language": "fr"}


def _twitch_routes(over=None):
    routes = {
        ("POST", "/oauth2/token"): [_token()],
        ("GET", "/helix/streams"): [
            (200, {"data": [_stream("1", "Jeu Alpha", 100), _stream("2", "Jeu Beta", 50)],
                   "pagination": {"cursor": "c1"}}),
            (200, {"data": [_stream("1", "Jeu Alpha", 30), _stream("", "", 999)], "pagination": {}}),
        ],
        ("GET", "/helix/games/top"): [(200, {"data": [{"id": "1", "name": "Jeu Alpha"}]})],
        ("GET", "/helix/videos"): [(200, {"data": [{
            "id": "v10", "url": "https://www.twitch.tv/videos/10", "title": "Soirée", "user_name": "streamer_a",
            "duration": "3h2m1s", "published_at": "2026-10-06T05:00:00Z", "view_count": 600,
            "type": "archive"}]})],
    }
    routes.update(over or {})
    return routes


def _twitch(tmp_path, http, **over):
    collector = veille_sources.default_collectors(http, clock=lambda: NOW)["twitch"]
    return collector(_settings(tmp_path, **over))


# -- durées -----------------------------------------------------------------


def test_twitch_duration_to_seconds():
    assert veille_sources.parse_twitch_duration("3h2m1s") == 10921
    assert veille_sources.parse_twitch_duration("45m") == 2700
    assert veille_sources.parse_twitch_duration("30s") == 30


def test_iso_duration_to_seconds():
    assert veille_sources.parse_iso_duration("PT1H2M3S") == 3723
    assert veille_sources.parse_iso_duration("PT15M") == 900


# -- (1) jeton Twitch -------------------------------------------------------


def test_token_via_client_credentials_cached_and_reused(tmp_path):
    http = FakeHttp(_twitch_routes())
    _twitch(tmp_path, http)
    _twitch(tmp_path, http)  # second relevé, même transport
    posts = http.to("/oauth2/token")
    assert len(posts) == 1
    assert posts[0]["params"] == {"client_id": "cid", "client_secret": SECRET, "grant_type": "client_credentials"}
    cached = json.loads((tmp_path / "state" / "veille" / "twitch_token.json").read_text(encoding="utf-8"))
    assert cached["access_token"] == "tok1"
    assert datetime.fromisoformat(cached["expires_at"]) == NOW + timedelta(seconds=3600)
    assert http.to("/helix/streams")[0]["headers"] == {"Client-Id": "cid", "Authorization": "Bearer tok1"}


def test_expired_cached_token_is_renewed(tmp_path):
    sdir = tmp_path / "state" / "veille"
    sdir.mkdir(parents=True)
    (sdir / "twitch_token.json").write_text(json.dumps(
        {"access_token": "old", "expires_at": (NOW - timedelta(seconds=1)).isoformat()}), encoding="utf-8")
    http = FakeHttp(_twitch_routes())
    _twitch(tmp_path, http)
    assert len(http.to("/oauth2/token")) == 1
    assert http.to("/helix/streams")[0]["headers"]["Authorization"] == "Bearer tok1"


def test_token_renewed_after_401(tmp_path):
    http = FakeHttp(_twitch_routes({
        ("POST", "/oauth2/token"): [_token("tok1"), _token("tok2")],
        ("GET", "/helix/streams"): [
            (401, {"error": "Unauthorized", "message": "Invalid OAuth token"}),
            (200, {"data": [_stream("1", "Jeu Alpha", 10)], "pagination": {}}),
        ],
    }))
    result = _twitch(tmp_path, http)
    assert len(http.to("/oauth2/token")) == 2
    assert [c["headers"]["Authorization"] for c in http.to("/helix/streams")] == ["Bearer tok1", "Bearer tok2"]
    assert result["games"] == [{"name": "Jeu Alpha", "viewers_fr": 10}]


def test_secret_in_no_file_and_no_error_message(tmp_path):
    http = FakeHttp(_twitch_routes({
        ("GET", "/helix/streams"): [(500, {"message": f"boom {SECRET} {YKEY}"})]}))
    with pytest.raises(veille_sources.SourceError) as err:
        _twitch(tmp_path, http)
    assert SECRET not in str(err.value) and "tok1" not in str(err.value)
    for path in (tmp_path / "state").rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8")


def test_secret_not_in_message_when_token_endpoint_fails(tmp_path):
    http = FakeHttp(_twitch_routes({("POST", "/oauth2/token"): [(400, {"message": f"invalid {SECRET}"})]}))
    with pytest.raises(veille_sources.SourceError) as err:
        _twitch(tmp_path, http)
    assert "HTTP 400" in str(err.value) and SECRET not in str(err.value)


def test_secret_not_in_message_when_transport_raises(tmp_path):
    http = FakeHttp(_twitch_routes({("POST", "/oauth2/token"): [RuntimeError(f"url ?client_secret={SECRET}")]}))
    with pytest.raises(veille_sources.SourceError) as err:
        _twitch(tmp_path, http)
    assert SECRET not in str(err.value)


# -- (2) Twitch : viewers et VOD --------------------------------------------


def test_viewers_fr_summed_over_cursor_pages(tmp_path):
    http = FakeHttp(_twitch_routes())
    result = _twitch(tmp_path, http)
    assert result["games"] == [{"name": "Jeu Alpha", "viewers_fr": 130}, {"name": "Jeu Beta", "viewers_fr": 50}]
    pages = http.to("/helix/streams")
    assert [p["params"].get("after") for p in pages] == [None, "c1"]
    assert all(p["params"]["language"] == "fr" and p["params"]["first"] == 100 for p in pages)
    assert http.to("/helix/games/top")[0]["params"] == {"first": 20}


def test_streams_pagination_stops_at_five_pages(tmp_path):
    http = FakeHttp(_twitch_routes({("GET", "/helix/streams"): lambda call: (
        200, {"data": [_stream("1", "Jeu Alpha", 1)], "pagination": {"cursor": "next"}})}))
    result = _twitch(tmp_path, http)
    assert len(http.to("/helix/streams")) == 5
    assert result["games"][0]["viewers_fr"] == 5


def test_vods_listed_for_top_games_with_documented_params(tmp_path):
    http = FakeHttp(_twitch_routes())
    result = _twitch(tmp_path, http, twitch_top_games=1, twitch_vods_per_game=7)
    calls = http.to("/helix/videos")
    assert len(calls) == 1  # un seul jeu (le plus regardé)
    assert calls[0]["params"] == {"game_id": "1", "language": "fr", "period": "day", "sort": "views",
                                  "type": "archive", "first": 7}
    assert result["vods"] == [{
        "video_id": "v10", "url": "https://www.twitch.tv/videos/10", "title": "Soirée",
        "channel_name": "streamer_a", "game_name": "Jeu Alpha", "duration_s": 10921,
        "published_at": "2026-10-06T05:00:00Z", "view_count": 600, "views_per_hour": 200.0}]


# -- (3) YouTube ------------------------------------------------------------


def _yt_item(video_id="y1", duration="PT1H2M3S", views="3000", published="2026-10-06T04:00:00Z", **snippet):
    item = {"id": video_id, "snippet": {"title": "T", "channelTitle": "chaine_a", "publishedAt": published, **snippet},
            "contentDetails": {"duration": duration}, "statistics": {"viewCount": views}}
    if views is None:
        del item["statistics"]["viewCount"]
    return item


def _youtube(tmp_path, http, **over):
    return veille_sources.default_collectors(http, clock=lambda: NOW)["youtube"](_settings(tmp_path, **over))


def test_youtube_single_videos_list_call_and_fields(tmp_path):
    http = FakeHttp({("GET", "/youtube/v3/videos"): [(200, {"items": [_yt_item()]})]})
    result = _youtube(tmp_path, http, youtube_max_results=25, region="BE")
    assert len(http.calls) == 1
    assert "search" not in http.calls[0]["url"]
    assert http.calls[0]["params"] == {
        "chart": "mostPopular", "regionCode": "BE", "videoCategoryId": "20",
        "part": "snippet,statistics,contentDetails", "maxResults": 25, "key": YKEY}
    assert result == {"videos": [{
        "video_id": "y1", "url": "https://www.youtube.com/watch?v=y1", "title": "T", "channel_name": "chaine_a",
        "game_name": None, "duration_s": 3723, "published_at": "2026-10-06T04:00:00Z", "view_count": 3000,
        "views_per_hour": 750.0}]}  # 4 h depuis la publication


def test_youtube_views_per_hour_floors_hours_at_one(tmp_path):
    http = FakeHttp({("GET", "/youtube/v3/videos"): [(200, {"items": [
        _yt_item(published=(NOW - timedelta(minutes=10)).isoformat(), views="500")]})]})
    assert _youtube(tmp_path, http)["videos"][0]["views_per_hour"] == 500.0


def test_youtube_hidden_view_count_is_null_and_live_skipped(tmp_path):
    http = FakeHttp({("GET", "/youtube/v3/videos"): [(200, {"items": [
        _yt_item("a", views=None), _yt_item("b", liveBroadcastContent="live")]})]})
    videos = _youtube(tmp_path, http)["videos"]
    assert [v["video_id"] for v in videos] == ["a"]
    assert videos[0]["view_count"] is None and videos[0]["views_per_hour"] is None


def test_youtube_key_not_in_error_url(tmp_path):
    http = FakeHttp({("GET", "/youtube/v3/videos"): [(403, {"error": {"message": f"quota {YKEY}"}})]})
    with pytest.raises(veille_sources.SourceError) as err:
        _youtube(tmp_path, http)
    text = str(err.value)
    assert "HTTP 403" in text and "/youtube/v3/videos" in text and "regionCode=FR" in text
    assert YKEY not in text and "key=" not in text


# -- (4) Steam --------------------------------------------------------------


def _steam_routes(applist_calls=None):
    return {
        ("GET", "/GetMostPlayedGames/v1/"): [(200, {"response": {"ranks": [
            {"rank": 1, "appid": 10, "peak_in_game": 900}, {"rank": 2, "appid": 20, "peak_in_game": 500},
            {"rank": 3, "appid": 30, "peak_in_game": 100}, {"rank": 4, "appid": 99, "peak_in_game": 50}]}})],
        ("GET", "/GetAppList/v2/"): [(200, {"applist": {"apps": [
            {"appid": 10, "name": "Jeu Alpha"}, {"appid": 20, "name": "Jeu Beta"}, {"appid": 30, "name": "Gamma"}]}})],
    }


def _steam(tmp_path, http, clock=lambda: NOW, **over):
    return veille_sources.default_collectors(http, clock=clock)["steam"](_settings(tmp_path, **over))


def test_steam_top_names_and_no_key_sent(tmp_path):
    http = FakeHttp(_steam_routes())
    result = _steam(tmp_path, http, steam_top=3)
    assert result == {"games": [{"appid": "10", "name": "Jeu Alpha", "players": 900},
                                {"appid": "20", "name": "Jeu Beta", "players": 500},
                                {"appid": "30", "name": "Gamma", "players": 100}]}
    for call in http.calls:
        assert "key" not in call["params"] and "Authorization" not in call["headers"]


def test_steam_game_without_name_is_not_reported(tmp_path):
    result = _steam(tmp_path, FakeHttp(_steam_routes()), steam_top=100)
    assert "99" not in [g["appid"] for g in result["games"]]


def test_applist_read_at_most_once_per_day(tmp_path):
    http = FakeHttp(_steam_routes())
    _steam(tmp_path, http)
    _steam(tmp_path, http, clock=lambda: NOW + timedelta(hours=2))
    assert len(http.to("/GetAppList/v2/")) == 1
    _steam(tmp_path, http, clock=lambda: NOW + timedelta(days=1))
    assert len(http.to("/GetAppList/v2/")) == 2


def test_current_players_for_one_appid(tmp_path):
    http = FakeHttp({("GET", "/GetNumberOfCurrentPlayers/v1/"): [(200, {"response": {"player_count": 4242, "result": 1}})]})
    assert veille_sources.current_players(_settings(tmp_path), 440, http=http) == 4242
    assert http.calls[0]["params"] == {"appid": 440}


# -- (5) erreurs ------------------------------------------------------------


def test_non_2xx_error_has_code_url_and_snippet(tmp_path):
    http = FakeHttp(_steam_routes())
    http.routes[("GET", "/GetMostPlayedGames/v1/")] = [(403, {"message": "Forbidden" + "x" * 500})]
    with pytest.raises(veille_sources.SourceError) as err:
        _steam(tmp_path, http)
    text = str(err.value)
    assert "HTTP 403" in text and "GetMostPlayedGames/v1/" in text and "Forbidden" in text
    assert len(text) < 500


def test_unreadable_json_is_a_source_error(tmp_path):
    http = FakeHttp(_steam_routes())
    http.routes[("GET", "/GetMostPlayedGames/v1/")] = [(200, "<html>pas du json</html>")]
    with pytest.raises(veille_sources.SourceError, match="illisible.*pas du json"):
        _steam(tmp_path, http)


def test_missing_field_is_a_source_error(tmp_path):
    http = FakeHttp({("GET", "/youtube/v3/videos"): [(200, {"unexpected": []})]})
    with pytest.raises(veille_sources.SourceError, match="champ attendu absent.*items"):
        _youtube(tmp_path, http)


def test_default_transport_wraps_network_errors_without_params(monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError(f"refused {SECRET}")

    monkeypatch.setattr(httpx, "request", boom)
    with pytest.raises(veille_sources.SourceError) as err:
        veille_sources.default_http("GET", "https://example.test/x", params={"key": SECRET}, timeout_s=1)
    assert SECRET not in str(err.value) and "ConnectError" in str(err.value)


def test_collect_integration_source_error_ranged_as_status_error(tmp_path, monkeypatch):
    config = _config(tmp_path)
    routes = {**_twitch_routes(), **_steam_routes(),
              ("GET", "/youtube/v3/videos"): [(500, {"error": f"boom {YKEY}"})]}
    http = FakeHttp(routes)
    monkeypatch.setattr(veille_sources, "default_http", http)
    state = veille.collect(NOW, config=config)  # aucun collecteur injecté : les réels
    assert state["sources"]["youtube"]["status"] == "error"
    assert "HTTP 500" in state["sources"]["youtube"]["error"]
    assert state["sources"]["twitch"]["status"] == "ok" and state["sources"]["steam"]["status"] == "ok"
    for path in (tmp_path / "state").rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert SECRET not in text and YKEY not in text


# -- (6) tests réels optionnels ---------------------------------------------

_REAL = os.environ.get("CLIPPER_REAL_NETWORK") == "1"
real_only = pytest.mark.skipif(not _REAL, reason="CLIPPER_REAL_NETWORK=1 requis (réseau réel)")


def _real_settings(tmp_path):
    return _settings(tmp_path, twitch_client_id=os.environ.get("TWITCH_CLIENT_ID", ""),
                     twitch_client_secret=os.environ.get("TWITCH_CLIENT_SECRET", ""),
                     youtube_api_key=os.environ.get("YOUTUBE_API_KEY", ""))


@real_only
def test_real_twitch(tmp_path):
    settings = _real_settings(tmp_path)
    if not settings["twitch_client_id"]:
        pytest.skip("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET absents")
    assert veille_sources.default_collectors()["twitch"](settings)["games"]


@real_only
def test_real_youtube(tmp_path):
    settings = _real_settings(tmp_path)
    if not settings["youtube_api_key"]:
        pytest.skip("YOUTUBE_API_KEY absente")
    assert "videos" in veille_sources.default_collectors()["youtube"](settings)


@real_only
def test_real_steam(tmp_path):
    assert veille_sources.default_collectors()["steam"](_settings(tmp_path, steam_top=5))["games"]
