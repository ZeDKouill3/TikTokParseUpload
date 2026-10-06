"""Collecteurs réels de la veille : Twitch Helix, YouTube Data API v3, Steam Web API
(ADR-ca9a, SPEC-bdd9 R3).

Bibliothèque : aucun import de ``clipper.web`` ni d'une étape, aucun import de
``clipper.veille`` (c'est elle qui importe ce module). Toutes les requêtes
passent par un transport injectable ::

    http(method, url, *, params, headers, timeout_s) -> (status, body)

``body`` est le JSON décodé, ou le texte brut si la réponse n'est pas du JSON
(le collecteur lève alors une ``SourceError``). Le transport par défaut
(``default_http``) s'appuie sur httpx.

Les collecteurs rendent les formes décrites dans ``clipper.veille``. Une
``SourceError`` porte le code HTTP, l'URL sans paramètre secret et le début de
la réponse ; aucun secret (clé API, secret client, jeton) n'apparaît dans un
message ni dans un fichier d'état (R3).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from clipper import channel as channel_mod

Http = Callable[..., "tuple[int, Any]"]
Clock = Callable[[], datetime]

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_API = "https://api.twitch.tv/helix"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
STEAM_API = "https://api.steampowered.com"
STEAM_SELLERS_URL = f"{STEAM_API}/IStoreTopSellersService/GetWeeklyTopSellers/v1/"
# Code de langue [veille] language -> nom de langue attendu par l'API magasin (autres valeurs passées telles quelles).
_STEAM_LANGUAGES = {"fr": "french", "en": "english", "de": "german", "es": "spanish", "it": "italian", "pt": "portuguese"}
STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"  # GetAppList v2 retiré par Valve (404)

STREAM_PAGES_MAX = 5
_TOKEN_MARGIN = timedelta(seconds=60)
_SECRET_PARAMS = {"key", "client_secret", "access_token"}
_SNIPPET_CHARS = 200

_TWITCH_DURATION = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


class SourceError(Exception):
    """Une source n'a pas pu être relevée (HTTP, JSON, champ absent)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


def default_http(method: str, url: str, *, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, timeout_s: float = 20) -> tuple[int, Any]:
    """Transport httpx. Une erreur réseau devient une ``SourceError`` sans paramètres."""
    try:
        response = httpx.request(method, url, params=params, headers=headers, timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise SourceError(f"requête impossible sur {url} ({type(exc).__name__})") from None
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text


def _safe_url(url: str, params: dict[str, Any] | None) -> str:
    public = {k: v for k, v in (params or {}).items() if k not in _SECRET_PARAMS}
    return f"{url}?{urlencode(public)}" if public else url


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


class _Client:
    """Appelle le transport et traduit tout échec en ``SourceError`` expurgée."""

    def __init__(self, http: Http, timeout_s: float, secrets: tuple[str, ...]):
        self.http, self.timeout_s, self.secrets = http, timeout_s, secrets

    def request(self, method: str, url: str, params: dict[str, Any] | None = None,
                headers: dict[str, str] | None = None, *, accept_401: bool = False) -> tuple[int, Any]:
        """``(status, body JSON)`` ; 401 rendu tel quel seulement si ``accept_401``."""
        shown = _safe_url(url, params)
        try:
            status, body = self.http(method, url, params=params, headers=headers, timeout_s=self.timeout_s)
        except SourceError:
            raise
        except Exception as exc:  # le transport injecté peut lever n'importe quoi
            raise SourceError(_redact(f"requête impossible sur {shown} ({type(exc).__name__} : {exc})",
                                      self.secrets)) from None
        if accept_401 and status == 401:
            return status, body
        snippet = _redact(str(body)[:_SNIPPET_CHARS], self.secrets)
        if not 200 <= status < 300:
            raise SourceError(f"HTTP {status} sur {shown} : {snippet}")
        if not isinstance(body, (dict, list)):
            raise SourceError(f"HTTP {status} sur {shown} : réponse JSON illisible : {snippet}")
        return status, body

    def fail(self, url: str, params: dict[str, Any] | None, body: Any, what: str) -> SourceError:
        snippet = _redact(str(body)[:_SNIPPET_CHARS], self.secrets)
        return SourceError(f"champ attendu absent ({what}) sur {_safe_url(url, params)} : {snippet}")


def _field(client: _Client, url: str, params: dict[str, Any] | None, body: Any, *path: str) -> Any:
    cur = body
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            raise client.fail(url, params, body, ".".join(path))
        cur = cur[key]
    return cur


# --------------------------------------------------------------------------
# Durées et dates
# --------------------------------------------------------------------------


def parse_twitch_duration(text: str) -> int:
    """« 3h2m1s » → 10921, « 45m » → 2700."""
    match = _TWITCH_DURATION.match(text or "")
    if not match or not text:
        raise SourceError(f"durée Twitch illisible : {text!r}")
    h, m, s = (int(g or 0) for g in match.groups())
    return h * 3600 + m * 60 + s


def parse_iso_duration(text: str) -> int:
    """ISO 8601 « PT1H2M3S » → 3723."""
    match = _ISO_DURATION.match(text or "")
    if not match:
        raise SourceError(f"durée ISO 8601 illisible : {text!r}")
    d, h, m, s = (int(g or 0) for g in match.groups())
    return d * 86400 + h * 3600 + m * 60 + s


TWITCH_THUMB_SIZE = ("640", "360")


def _twitch_thumbnail(raw: Any) -> str | None:
    """URL de miniature d'une VOD Twitch à taille fixe ; ``None`` si absente, vide ou en cours de traitement."""
    if not isinstance(raw, str) or not raw or "404_processing" in raw:
        return None
    return raw.replace("%{width}", TWITCH_THUMB_SIZE[0]).replace("%{height}", TWITCH_THUMB_SIZE[1])


def _youtube_thumbnail(thumbnails: Any) -> str | None:
    """La plus grande miniature de ``snippet.thumbnails`` ; ``None`` si aucune."""
    if not isinstance(thumbnails, dict):
        return None
    sized = [t for t in thumbnails.values() if isinstance(t, dict) and t.get("url")]
    if not sized:
        return None
    return str(max(sized, key=lambda t: int(t.get("width") or 0))["url"])


def _views_per_hour(view_count: int | None, published_at: str, now: datetime) -> float | None:
    if view_count is None:
        return None
    hours = (now - datetime.fromisoformat(published_at)).total_seconds() / 3600
    return view_count / max(1.0, hours)


def _read_json(path: Path) -> Any:
    """Cache illisible ou absent : ``None`` (le cache se refait, ce n'est pas une donnée)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sdir(settings: dict[str, object]) -> Path:
    return Path(str(settings["state_dir"]))


def _client(settings: dict[str, object], http: Http, secrets: tuple[str, ...]) -> _Client:
    return _Client(http, float(settings["http_timeout_s"]), secrets)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Twitch
# --------------------------------------------------------------------------


class _Twitch:
    def __init__(self, settings: dict[str, object], http: Http, clock: Clock):
        self.settings, self.clock = settings, clock
        self.client_id = str(settings["twitch_client_id"])
        self.secret = str(settings["twitch_client_secret"])
        self.client = _client(settings, http, (self.secret,))
        self.token_path = _sdir(settings) / "twitch_token.json"
        self.token: str | None = None

    def _cached_token(self) -> str | None:
        data = _read_json(self.token_path)
        try:
            if datetime.fromisoformat(data["expires_at"]) - _TOKEN_MARGIN > self.clock():
                return str(data["access_token"])
        except (KeyError, TypeError, ValueError):
            pass
        return None

    def _fetch_token(self) -> str:
        params = {"client_id": self.client_id, "client_secret": self.secret, "grant_type": "client_credentials"}
        _, body = self.client.request("POST", TWITCH_TOKEN_URL, params)
        token = str(_field(self.client, TWITCH_TOKEN_URL, params, body, "access_token"))
        expires_in = int(_field(self.client, TWITCH_TOKEN_URL, params, body, "expires_in"))
        self.client.secrets += (token,)
        path = self.token_path
        with channel_mod.file_lock(path):
            channel_mod.atomic_write_json(path, {
                "access_token": token, "expires_at": (self.clock() + timedelta(seconds=expires_in)).isoformat()})
        return token

    def ensure_token(self) -> str:
        if self.token is None:
            self.token = self._cached_token() or self._fetch_token()
            self.client.secrets += (self.token,)
        return self.token

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{TWITCH_API}/{path}"
        for attempt in (1, 2):
            headers = {"Client-Id": self.client_id, "Authorization": f"Bearer {self.ensure_token()}"}
            status, body = self.client.request("GET", url, params, headers, accept_401=attempt == 1)
            if status != 401:
                break
            self.token = None  # jeton refusé : un seul renouvellement, puis on réessaie
            self.token_path.unlink(missing_ok=True)
        if not isinstance(body, dict):
            raise self.client.fail(url, params, body, "objet JSON")
        return body


def _twitch_collector(http: Http, clock: Clock) -> Callable[[dict[str, object]], dict[str, Any]]:
    def collect(settings: dict[str, object]) -> dict[str, Any]:
        api = _Twitch(settings, http, clock)
        language = str(settings["language"])
        now = clock()

        viewers: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        for _ in range(STREAM_PAGES_MAX):
            params: dict[str, Any] = {"language": language, "first": 100}
            if cursor:
                params["after"] = cursor
            body = api.get("streams", params)
            for stream in _field(api.client, f"{TWITCH_API}/streams", params, body, "data"):
                game_id = stream.get("game_id")
                if not game_id:
                    continue
                entry = viewers.setdefault(str(game_id), {"name": stream.get("game_name"), "viewers_fr": 0})
                entry["viewers_fr"] += int(stream.get("viewer_count", 0))
            cursor = (body.get("pagination") or {}).get("cursor")
            if not cursor:
                break

        top_params = {"first": int(settings["twitch_top_games"])}  # type: ignore[call-overload]
        top = api.get("games/top", top_params)
        names = {str(g["id"]): g["name"] for g in _field(api.client, f"{TWITCH_API}/games/top", top_params, top, "data")
                 if "id" in g and "name" in g}
        for game_id, entry in viewers.items():
            entry["name"] = entry["name"] or names.get(game_id)
        named = {gid: e for gid, e in viewers.items() if e["name"]}  # un jeu sans nom n'est pas relevé
        ranked = sorted(named.items(), key=lambda kv: (-kv[1]["viewers_fr"], kv[1]["name"]))

        vods: list[dict[str, Any]] = []
        private_vods = 0
        for game_id, entry in ranked[: int(settings["twitch_top_games"])]:  # type: ignore[call-overload]
            params = {"game_id": game_id, "language": language, "period": "day", "sort": "views",
                      "type": "archive", "first": int(settings["twitch_vods_per_game"])}  # type: ignore[call-overload]
            body = api.get("videos", params)
            for video in _field(api.client, f"{TWITCH_API}/videos", params, body, "data"):
                where = f"{TWITCH_API}/videos"
                for key in ("id", "url", "duration", "published_at"):
                    if key not in video:
                        raise api.client.fail(where, params, video, f"data[].{key}")
                if video.get("viewable", "public") != "public":
                    private_vods += 1  # réservée aux abonnés ou privée : jamais proposée
                    continue
                view_count = video.get("view_count")
                vods.append({
                    "video_id": str(video["id"]), "url": video["url"], "title": video.get("title"),
                    "channel_name": video.get("user_name"), "game_name": entry["name"],
                    "duration_s": parse_twitch_duration(video["duration"]),
                    "published_at": video["published_at"], "view_count": view_count,
                    "thumbnail_url": _twitch_thumbnail(video.get("thumbnail_url")),
                    "views_per_hour": _views_per_hour(view_count, video["published_at"], now),
                })
        return {"games": [{"name": e["name"], "viewers_fr": e["viewers_fr"]} for _, e in ranked], "vods": vods,
                "private_vods": private_vods}

    return collect


# --------------------------------------------------------------------------
# YouTube
# --------------------------------------------------------------------------


def _youtube_collector(http: Http, clock: Clock) -> Callable[[dict[str, object]], dict[str, Any]]:
    def collect(settings: dict[str, object]) -> dict[str, Any]:
        api_key = str(settings["youtube_api_key"])
        client = _client(settings, http, (api_key,))
        params = {"chart": "mostPopular", "regionCode": str(settings["region"]), "videoCategoryId": "20",
                  "part": "snippet,statistics,contentDetails",
                  "maxResults": int(settings["youtube_max_results"]), "key": api_key}  # type: ignore[call-overload]
        _, body = client.request("GET", YOUTUBE_VIDEOS_URL, params)
        now = clock()
        videos: list[dict[str, Any]] = []
        for item in _field(client, YOUTUBE_VIDEOS_URL, params, body, "items"):
            video_id = _field(client, YOUTUBE_VIDEOS_URL, params, item, "id")
            snippet = _field(client, YOUTUBE_VIDEOS_URL, params, item, "snippet")
            published_at = _field(client, YOUTUBE_VIDEOS_URL, params, snippet, "publishedAt")
            duration = _field(client, YOUTUBE_VIDEOS_URL, params, item, "contentDetails", "duration")
            if snippet.get("liveBroadcastContent") in ("live", "upcoming"):
                continue  # un direct n'est pas une VOD
            raw_views = (item.get("statistics") or {}).get("viewCount")  # masqué : null, jamais 0
            view_count = int(raw_views) if raw_views is not None else None
            videos.append({
                "video_id": str(video_id), "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet.get("title"), "channel_name": snippet.get("channelTitle"),
                "game_name": None, "duration_s": parse_iso_duration(duration),
                "published_at": published_at, "view_count": view_count,
                "thumbnail_url": _youtube_thumbnail(snippet.get("thumbnails")),
                "views_per_hour": _views_per_hour(view_count, published_at, now),
            })
        return {"videos": videos}

    return collect


# --------------------------------------------------------------------------
# Steam
# --------------------------------------------------------------------------


def _steam_name(client: _Client, appid: str) -> str:
    """Nom d'une app par l'API magasin (sans clé) ; ``SourceError`` dit pourquoi il manque."""
    params = {"appids": appid, "filters": "basic"}
    _, body = client.request("GET", STEAM_APPDETAILS_URL, params)
    entry = body.get(appid) if isinstance(body, dict) else None
    if not isinstance(entry, dict) or not entry.get("success"):
        raise SourceError(f"nom introuvable : appdetails ne connaît pas l'app {appid} (success=false)")
    name = (entry.get("data") or {}).get("name")
    if not isinstance(name, str) or not name:
        raise client.fail(STEAM_APPDETAILS_URL, params, body, f"{appid}.data.name")
    return name


def _steam_collector(http: Http, clock: Clock) -> Callable[[dict[str, object]], dict[str, Any]]:
    def collect(settings: dict[str, object]) -> dict[str, Any]:
        client = _client(settings, http, ())
        url = f"{STEAM_API}/ISteamChartsService/GetMostPlayedGames/v1/"
        _, body = client.request("GET", url, {})
        ranks = _field(client, url, {}, body, "response", "ranks")
        path = _sdir(settings) / "steam_names.json"  # un nom connu ne se redemande jamais
        cached = _read_json(path)
        names: dict[str, str] = dict(cached["names"]) if isinstance(cached, dict) and isinstance(cached.get("names"), dict) else {}
        lookups_left = int(settings["steam_name_lookups_max"])  # type: ignore[call-overload]
        games: list[dict[str, Any]] = []
        unnamed: list[dict[str, str]] = []
        learned = False
        for rank in ranks[: int(settings["steam_top"])]:  # type: ignore[call-overload]
            appid = str(_field(client, url, {}, rank, "appid"))
            players = _field(client, url, {}, rank, "peak_in_game")  # pic du jour : seul chiffre du classement
            place = rank.get("rank")
            last_week = rank.get("last_week_rank")  # 0 : absent du top la semaine dernière ; champ absent : inconnu
            if appid not in names:
                if lookups_left <= 0:
                    unnamed.append({"appid": appid, "reason": f"nom non demandé : limite de {int(settings['steam_name_lookups_max'])} requêtes appdetails par relevé atteinte"})  # type: ignore[call-overload]
                    continue
                lookups_left -= 1
                try:
                    names[appid] = _steam_name(client, appid)
                    learned = True
                except SourceError as exc:  # sans nom, pas de correspondance Twitch : non relevé, raison gardée
                    unnamed.append({"appid": appid, "reason": str(exc)})
                    continue
            games.append({"appid": appid, "name": names[appid], "players": players,
                          "rank": place if isinstance(place, int) else None,
                          "last_week_rank": last_week if isinstance(last_week, int) else None})
        if learned:
            with channel_mod.file_lock(path):
                channel_mod.atomic_write_json(path, {"names": names})
        return {"games": games, "unnamed": unnamed}

    return collect


def _steam_sellers_collector(http: Http, clock: Clock) -> Callable[[dict[str, object]], dict[str, Any]]:
    """Top des ventes de la semaine du pays ``[veille] region`` (sans clé) ; noms fournis par l'API elle-même."""
    def collect(settings: dict[str, object]) -> dict[str, Any]:
        client = _client(settings, http, ())
        country = str(settings["region"]).upper()
        language = _STEAM_LANGUAGES.get(str(settings["language"]).lower(), str(settings["language"]))
        params = {"input_json": json.dumps({
            "country_code": country, "page_start": 0, "page_count": int(settings["steam_sellers_top"]),  # type: ignore[call-overload]
            "context": {"language": language, "country_code": country},
            "data_request": {"include_basic_info": False}}, separators=(",", ":"))}
        _, body = client.request("GET", STEAM_SELLERS_URL, params)
        games: list[dict[str, Any]] = []
        for rank in _field(client, STEAM_SELLERS_URL, params, body, "response", "ranks"):
            name = _field(client, STEAM_SELLERS_URL, params, rank, "item", "name")
            last_week = rank.get("last_week_rank")  # absent ou 0 : pas dans le top la semaine dernière
            games.append({"appid": str(_field(client, STEAM_SELLERS_URL, params, rank, "appid")), "name": name,
                          "rank": _field(client, STEAM_SELLERS_URL, params, rank, "rank"),
                          "last_week_rank": last_week if isinstance(last_week, int) else 0})
        return {"games": games}

    return collect


def current_players(settings: dict[str, object], appid: str | int, *, http: Http | None = None) -> int:
    """Joueurs en ce moment d'une app (``GetNumberOfCurrentPlayers``, sans clé)."""
    client = _client(settings, http or default_http, ())
    url = f"{STEAM_API}/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
    params = {"appid": appid}
    _, body = client.request("GET", url, params)
    return int(_field(client, url, params, body, "response", "player_count"))


def default_collectors(http: Http | None = None, clock: Clock | None = None) -> dict[str, Callable[[dict[str, object]], dict[str, Any]]]:
    """Les collecteurs réels, sur le transport (et l'horloge) donnés."""
    http = http or default_http
    clock = clock or _now
    return {"twitch": _twitch_collector(http, clock), "youtube": _youtube_collector(http, clock),
            "steam": _steam_collector(http, clock), "steam_fr": _steam_sellers_collector(http, clock)}
