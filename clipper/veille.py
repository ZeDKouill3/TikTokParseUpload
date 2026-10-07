"""Veille des sujets chauds : relevé quotidien (ADR-ca9a, SPEC-bdd9 R1, R2, R4, R5).

Bibliothèque, pas une étape (ADR-b16b) : rien sous ``workspace/<video_id>/``,
aucun import de ``clipper.web`` ni d'une étape. Tout l'état est en JSON sous
``state/veille/`` (écriture atomique sous verrou) :

    history/<date>.json   relevé du jour (viewers Twitch, joueurs Steam, YouTube)
    days/<date>.json      sources, jeux, candidats, exclus, llm, propositions
    seen.json             VOD déjà mises en file ou ignorées
    selection/<date>.json meilleurs clips du jour (gardés / archivés / restaurés)
    refresh.json          demande de relevé immédiat (déposée par l'interface)

Les collecteurs sont injectés : ``collectors = {"twitch", "youtube", "steam"}``,
chacun un callable ``collector(settings) -> dict`` (``settings`` = la table
``[veille]`` fusionnée). Contrat de retour :

    twitch  {"games": [{"name", "viewers_fr"}],
             "vods":  [VOD]}
    youtube {"videos": [VOD]}
    steam   {"games": [{"appid", "name", "players", "rank", "last_week_rank"}],
             "unnamed": [{"appid", "reason"}]}  (optionnel : jeux sans nom, avec leur raison)
    steam_fr {"games": [{"appid", "name", "rank", "last_week_rank"}]}  (top des ventes du pays ``region`` ;
             ``last_week_rank`` 0 = absent du top la semaine dernière)
    igdb    {"games": [{"igdb_id", "name", "slug", "url", "hypes" (entier), "first_release_date" | None,
             "cover_image_id" | None, "steam_appid" | None, "release_dates": [{"date" (YYYY-MM-DD, jour UTC), "ts",
             "human", "platform", "region", "status", "date_format"}]}], "skipped_rows": n}  (SPEC-df51 R12 ;
             un jeu Twitch porte en plus ``igdb_id``, chaîne vide si Twitch ne l'a pas)

avec ``VOD = {video_id, url, title, channel_name, game_name | None,
duration_s, published_at (ISO 8601), view_count, views_per_hour}``. Un direct
en cours n'est pas une VOD : le collecteur ne le rend pas. Un collecteur qui
lève, ou dont la réponse est inexploitable, met sa source en ``error`` ; les
autres continuent (ADR-ad2e : aucun chiffre inventé, une donnée absente est
``null``). Sans collecteurs injectés, ``clipper.veille_sources`` fournit les réels.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clipper import channel as channel_mod
from clipper import llm, publish, veille_sources
from clipper.config import Config, load_config

CONFIG_DEFAULTS: dict[str, object] = {
    "enabled": False,
    "run_at": "07:00",
    "timezone": "Europe/Paris",
    "language": "fr",
    "region": "FR",
    "taste": "",
    "max_vods_per_day": 3,
    "best_clips_per_day": 3,
    "baseline_days": 7,
    "history_days": 90,
    "rise_min_pct": 50,
    "vod_min_duration_s": 1800,
    "vod_max_age_h": 36,
    "twitch_top_games": 20,
    "twitch_vods_per_game": 10,
    "youtube_max_results": 50,
    "youtube_min_duration_s": 600,
    "steam_top": 100,
    "steam_name_lookups_max": 100,
    "twitch_access_check_max": 30,
    "steam_sellers_top": 50,
    "twitch_client_id": "",
    "twitch_client_secret": "",
    "youtube_api_key": "",
    "state_dir": "state/veille",
    "http_timeout_s": 20,
    "steam_rank_gain_min": 5,
    "steam_risers_max": 10,
    "upcoming_days": 14,
    "release_window_days": 15,
    "igdb_min_hypes": 5,
    "igdb_recent_max": 12,
    "igdb_upcoming_max": 20,
    "igdb_pages_max": 4,
    "youtube_game_min_chars": 5,
}

# Clés retirées qu'un config.toml peut encore porter : ignorées à la lecture (clipper.config).
LEGACY_KEYS = ("igdb_releases_max",)  # SPEC-4efa, remplacée par igdb_recent_max / igdb_upcoming_max (SPEC-df51 R11)

log = logging.getLogger(__name__)

SOURCES = ("twitch", "youtube", "steam", "steam_fr", "igdb")
Collector = Callable[[dict[str, object]], dict[str, Any]]

# Clés exigées par source (steam n'en demande aucune).
_REQUIRED_KEYS = {
    "twitch": ("twitch_client_id", "twitch_client_secret"),
    "youtube": ("youtube_api_key",),
    "steam": (),
    "steam_fr": (),
    "igdb": ("twitch_client_id", "twitch_client_secret"),  # même jeton d'app que Twitch (ADR-798c)
}
_RUN_AT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATE_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


class VeilleError(Exception):
    """Réglage invalide ou fichier d'état illisible."""


# --------------------------------------------------------------------------
# Réglages
# --------------------------------------------------------------------------


def settings(config: Config) -> dict[str, object]:
    """Table ``[veille]`` validée (R1) ; ``VeilleError`` nomme la clé fautive."""
    table = config.section("veille")
    for key in ("max_vods_per_day", "best_clips_per_day", "baseline_days"):
        value = table[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise VeilleError(f"[veille] {key} doit être un entier >= 1 (reçu {value!r})")
    access_max = table["twitch_access_check_max"]
    if not isinstance(access_max, int) or isinstance(access_max, bool) or access_max < 0:
        raise VeilleError(f"[veille] twitch_access_check_max doit être un entier >= 0 (reçu {access_max!r})")
    for key, minimum in (("upcoming_days", 1), ("release_window_days", 0), ("igdb_min_hypes", 1),
                         ("igdb_recent_max", 1), ("igdb_upcoming_max", 1), ("igdb_pages_max", 1)):
        value = table[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise VeilleError(f"[veille] {key} doit être un entier >= {minimum} (reçu {value!r})")
    min_chars = table["youtube_game_min_chars"]
    if not isinstance(min_chars, int) or isinstance(min_chars, bool) or min_chars < 1:
        raise VeilleError(f"[veille] youtube_game_min_chars doit être un entier >= 1 (reçu {min_chars!r})")
    history_days = table["history_days"]
    if not isinstance(history_days, int) or isinstance(history_days, bool) or history_days < table["baseline_days"]:
        raise VeilleError(
            f"[veille] history_days doit être un entier >= baseline_days={table['baseline_days']} (reçu {history_days!r})")
    run_at = table["run_at"]
    if not isinstance(run_at, str) or not _RUN_AT.match(run_at):
        raise VeilleError(f"[veille] run_at doit être au format HH:MM (reçu {run_at!r})")
    try:
        ZoneInfo(str(table["timezone"]))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise VeilleError(f"[veille] timezone inconnu : {table['timezone']!r}") from exc
    return table


def _state_dir(table: dict[str, object]) -> Path:
    return Path(str(table["state_dir"]))


# --------------------------------------------------------------------------
# Fichiers
# --------------------------------------------------------------------------


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise VeilleError(f"fichier d'état de la veille illisible : {path.name} ({exc})") from exc


def _write(path: Path, data: Any) -> None:
    with channel_mod.file_lock(path):
        channel_mod.atomic_write_json(path, data)


def _seen_video_ids(sdir: Path) -> set[str]:
    seen = _read_json(sdir / "seen.json", {"queued": [], "ignored": []})
    try:
        return {e["video_id"] for key in ("queued", "ignored") for e in seen.get(key, [])}
    except (AttributeError, KeyError, TypeError) as exc:
        raise VeilleError(f"fichier d'état de la veille illisible : seen.json ({exc})") from exc


def _queue_video_ids(config: Config) -> set[str]:
    path = Path(str(config.section("worker")["queue_path"]))
    entries = _read_json(path, [])
    try:
        return {e["video_id"] for e in entries}
    except (KeyError, TypeError) as exc:
        raise VeilleError(f"file d'attente illisible : {path.name} ({exc})") from exc


def _load_history(sdir: Path, today: date, baseline_days: int) -> list[dict[str, Any]]:
    """Les ``baseline_days`` relevés précédents les plus récents (plus ancien d'abord)."""
    folder = sdir / "history"
    if not folder.exists():
        return []
    previous = sorted(p for p in folder.iterdir() if _DATE_FILE.match(p.name) and p.stem < today.isoformat())
    return [_read_json(p, None) for p in previous[-baseline_days:]]


def _prune_history(sdir: Path, today: date, history_days: int) -> None:
    folder = sdir / "history"
    if not folder.exists():
        return
    limit = (today - timedelta(days=history_days)).isoformat()
    for path in folder.iterdir():
        if _DATE_FILE.match(path.name) and path.stem < limit:
            path.unlink()


# --------------------------------------------------------------------------
# Jeux et montée (R4)
# --------------------------------------------------------------------------


def normalize(name: str) -> str:
    """Clé de jeu : minuscules, sans accents ni ponctuation, espaces réduits."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _delta(today: float | None, avg_values: list[float]) -> tuple[float | None, int | None]:
    """(moyenne, delta en %) ; delta null avec moins de 2 relevés ou une moyenne nulle."""
    if today is None or len(avg_values) < 2:
        return _mean(avg_values), None
    avg = _mean(avg_values)
    if not avg:
        return avg, None
    return avg, round((today - avg) / avg * 100)


def _rank_signal(info: dict[str, Any] | None) -> tuple[int | None, bool | None]:
    """Montée immédiate Steam : ``(gain de rang vs semaine dernière, nouveau dans le top)``.
    ``last_week_rank`` 0 = absent du top la semaine dernière (nouveau, pas de gain chiffré) ;
    rang inconnu (champ absent, jeu non relevé) = ``(None, None)``, jamais inventé."""
    if not info or not isinstance(info.get("rank"), int) or not isinstance(info.get("last_week_rank"), int):
        return None, None
    if info["last_week_rank"] <= 0:
        return None, True
    return info["last_week_rank"] - info["rank"], False


def _sellers_signal(info: dict[str, Any] | None) -> dict[str, Any]:
    """Champs « ventes du pays » d'un jeu : rang, rang de la semaine dernière, gain de places, nouveau dans le top.
    ``last_week_rank`` absent ou 0 = nouveau (pas de gain chiffré) ; jeu hors du top ventes = tout à ``None``."""
    if not info:
        return {"steam_sellers_rank": None, "steam_sellers_last_week_rank": None,
                "steam_sellers_gain": None, "steam_sellers_new": None}
    last = info.get("last_week_rank")
    new = not isinstance(last, int) or last <= 0
    return {"steam_sellers_rank": info["rank"], "steam_sellers_last_week_rank": None if new else last,
            "steam_sellers_gain": None if new else last - info["rank"], "steam_sellers_new": new}


def _sellers_risers(
    sellers: dict[str, dict[str, Any]],
    known_keys: set[str],
    youtube: dict[str, dict[str, Any]],
    vod_counts: dict[str, int],
    previous: list[dict[str, Any]],
    table: dict[str, object],
) -> list[dict[str, Any]]:
    """Jeux qui montent dans le top ventes du pays (nouveau, ou gain >= ``steam_rank_gain_min``) et pas
    encore dans la liste (Twitch, Steam mondial) : champs Twitch/joueurs à null, jamais inventés."""
    gain_min = int(table["steam_rank_gain_min"])  # type: ignore[call-overload]
    risers: list[dict[str, Any]] = []
    for appid, info in sellers.items():
        key = normalize(info["name"])
        signal = _sellers_signal(info)
        if key in known_keys or not (signal["steam_sellers_new"] or signal["steam_sellers_gain"] >= gain_min):
            continue
        risers.append({
            "key": key, "name": info["name"], "source": "steam_fr", "twitch_match": False,
            "twitch_fr_viewers": None, "twitch_avg": None, "twitch_delta_pct": None,
            "steam_appid": appid, "steam_match": False, "steam_players": None,
            "steam_avg": None, "steam_delta_pct": None,
            "steam_rank": None, "steam_rank_gain": None, "steam_new_in_top": None, **signal,
            "youtube_views_per_hour": youtube.get(key, {}).get("views_per_hour_sum"),
            "vod_count": vod_counts.get(key, 0),
            "baseline_days_available": len(previous),
        })
    risers.sort(key=lambda g: (not g["steam_sellers_new"], g["steam_sellers_rank"] if g["steam_sellers_new"] else -g["steam_sellers_gain"]))
    return risers[: int(table["steam_risers_max"])]  # type: ignore[call-overload]


def _build_games(
    twitch: dict[str, dict[str, Any]],
    steam: dict[str, dict[str, Any]],
    youtube: dict[str, dict[str, Any]],
    vod_counts: dict[str, int],
    previous: list[dict[str, Any]],
    table: dict[str, object] | None = None,
    sellers: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    steam_by_key = {normalize(info["name"]): (appid, info) for appid, info in steam.items()}
    games: list[dict[str, Any]] = []
    for key, info in twitch.items():
        appid, steam_info = steam_by_key.get(key, (None, None))
        twitch_avg, twitch_delta = _delta(
            info["viewers_fr"], [p["twitch"][key]["viewers_fr"] for p in previous if key in p.get("twitch", {})])
        steam_values = [p["steam"][appid]["players"] for p in previous if appid and appid in p.get("steam", {})]
        steam_players = steam_info["players"] if steam_info else None
        steam_avg, steam_delta = _delta(steam_players, steam_values) if steam_info else (None, None)
        rank_gain, new_in_top = _rank_signal(steam_info)
        games.append({
            "key": key, "name": info["name"], "source": "twitch", "twitch_match": True,
            "twitch_fr_viewers": info["viewers_fr"], "twitch_avg": twitch_avg, "twitch_delta_pct": twitch_delta,
            "steam_appid": appid, "steam_match": steam_info is not None, "steam_players": steam_players,
            "steam_avg": steam_avg, "steam_delta_pct": steam_delta,
            "steam_rank": steam_info.get("rank") if steam_info else None,
            "steam_rank_gain": rank_gain, "steam_new_in_top": new_in_top,
            "youtube_views_per_hour": youtube.get(key, {}).get("views_per_hour_sum"),
            "vod_count": vod_counts.get(key, 0),
            "baseline_days_available": len(previous),
        })
    if table is not None:
        games.extend(_steam_risers(steam, set(twitch), youtube, vod_counts, previous, table))
    sellers_by_key = {normalize(info["name"]): info for info in (sellers or {}).values()}
    for game in games:  # fusion par clé normalisée : un jeu déjà présent porte les champs, jamais de doublon
        game.update(_sellers_signal(sellers_by_key.get(game["key"])))
    if table is not None and sellers:
        games.extend(_sellers_risers(sellers, {g["key"] for g in games}, youtube, vod_counts, previous, table))
    return games


def _steam_risers(
    steam: dict[str, dict[str, Any]],
    twitch_keys: set[str],
    youtube: dict[str, dict[str, Any]],
    vod_counts: dict[str, int],
    previous: list[dict[str, Any]],
    table: dict[str, object],
) -> list[dict[str, Any]]:
    """Jeux Steam qui montent sans être déjà dans la liste Twitch : nouveau dans le top, ou gain de rang
    >= ``steam_rank_gain_min``. Champs Twitch à null (jamais inventés), plafonné à ``steam_risers_max``.
    Rang ou semaine dernière inconnus : le jeu n'est pas retenu."""
    gain_min = int(table["steam_rank_gain_min"])  # type: ignore[call-overload]
    risers: list[dict[str, Any]] = []
    for appid, info in steam.items():
        key = normalize(info["name"])
        if key in twitch_keys:
            continue
        rank_gain, new_in_top = _rank_signal(info)
        if not (new_in_top or (rank_gain is not None and rank_gain >= gain_min)):
            continue
        steam_avg, steam_delta = _delta(
            info["players"], [p["steam"][appid]["players"] for p in previous if appid in p.get("steam", {})])
        risers.append({
            "key": key, "name": info["name"], "source": "steam", "twitch_match": False,
            "twitch_fr_viewers": None, "twitch_avg": None, "twitch_delta_pct": None,
            "steam_appid": appid, "steam_match": True, "steam_players": info["players"],
            "steam_avg": steam_avg, "steam_delta_pct": steam_delta,
            "steam_rank": info["rank"], "steam_rank_gain": rank_gain, "steam_new_in_top": new_in_top,
            "youtube_views_per_hour": youtube.get(key, {}).get("views_per_hour_sum"),
            "vod_count": vod_counts.get(key, 0),
            "baseline_days_available": len(previous),
        })
    # nouveaux dans le top d'abord (meilleur rang en tête), puis plus gros gains
    risers.sort(key=lambda g: (not g["steam_new_in_top"], g["steam_rank"] if g["steam_new_in_top"] else -g["steam_rank_gain"]))
    return risers[: int(table["steam_risers_max"])]  # type: ignore[call-overload]


# --------------------------------------------------------------------------
# Sorties de jeux IGDB (SPEC-4efa R13, R14)
# --------------------------------------------------------------------------


def _empty_releases() -> dict[str, Any]:
    return {"recent": [], "upcoming": [], "excluded_low_hypes": 0, "truncated": {"recent": 0, "upcoming": 0}}


_TREND_FIELDS = ("key", "name", "twitch_fr_viewers", "twitch_delta_pct", "steam_players", "steam_rank",
                 "steam_rank_gain", "steam_new_in_top", "steam_sellers_rank", "steam_sellers_gain", "steam_sellers_new")


def _classify_releases(games: list[dict[str, Any]], today: date, table: dict[str, object]) -> list[dict[str, Any]]:
    """Une entrée par jeu IGDB dont une date tombe dans la fenêtre J-``release_window_days`` .. J+``upcoming_days``
    (R13) : ``date`` = la plus ancienne date de la fenêtre ; ``portage`` = une date antérieure existe et une plateforme
    de la fenêtre n'y figure pas. Ni exclusion pour hypes, ni tendance, ni tri ici."""
    first = (today - timedelta(days=int(table["release_window_days"]))).isoformat()  # type: ignore[call-overload]
    last = (today + timedelta(days=int(table["upcoming_days"]))).isoformat()  # type: ignore[call-overload]
    entries: list[dict[str, Any]] = []
    for game in games:
        inside = sorted((d for d in game["release_dates"] if first <= d["date"] <= last), key=lambda d: d["date"])
        if not inside:
            continue
        earlier = [d for d in game["release_dates"] if d["date"] < first]
        earlier_platforms = {d["platform"] for d in earlier if d.get("platform")}
        portage = bool(earlier) and any(d["platform"] and d["platform"] not in earlier_platforms for d in inside)
        entries.append({
            "igdb_id": game["igdb_id"], "name": game["name"], "key": normalize(game["name"]), "slug": game.get("slug"),
            "url": game.get("url"), "hypes": game["hypes"], "cover_image_id": game.get("cover_image_id"),
            "steam_appid": game.get("steam_appid"), "first_release_date": game.get("first_release_date"),
            "date": inside[0]["date"], "human": inside[0].get("human"),
            "days": (date.fromisoformat(inside[0]["date"]) - today).days,
            "platforms": sorted({d["platform"] for d in inside if d.get("platform")}),
            "regions": sorted({d["region"] for d in inside if d.get("region")}),
            "statuses": sorted({d["status"] for d in inside if d.get("status")}),
            "portage": portage, "trend": None,
        })
    return entries


def _group_releases(entries: list[dict[str, Any]], games: list[dict[str, Any]], twitch_igdb: dict[str, str],
                    table: dict[str, object]) -> dict[str, Any]:
    """Attache la tendance (jeu du relevé du jour apparié par ``igdb_id`` Twitch puis par clé), écarte les jeux sous
    ``igdb_min_hypes`` sans tendance, trie par hypes et coupe : ``recent`` (days <= 0, ``igdb_recent_max``) et
    ``upcoming`` (days >= 1, ``igdb_upcoming_max``) (R13)."""
    by_key = {g["key"]: g for g in games}
    by_igdb = {igdb_id: by_key[key] for key, igdb_id in twitch_igdb.items() if igdb_id and key in by_key}
    min_hypes = int(table["igdb_min_hypes"])  # type: ignore[call-overload]
    recent: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    excluded = 0
    for entry in entries:
        game = by_igdb.get(entry["igdb_id"]) or by_key.get(entry["key"])
        trend = {k: game.get(k) for k in _TREND_FIELDS} if game else None
        if entry["hypes"] < min_hypes and trend is None:
            excluded += 1
            continue
        (recent if entry["days"] <= 0 else upcoming).append({**entry, "trend": trend})
    recent.sort(key=lambda e: (-e["hypes"], -e["days"], e["name"]))
    upcoming.sort(key=lambda e: (-e["hypes"], e["date"], e["name"]))
    cap_recent, cap_upcoming = int(table["igdb_recent_max"]), int(table["igdb_upcoming_max"])  # type: ignore[call-overload]
    return {"recent": recent[:cap_recent], "upcoming": upcoming[:cap_upcoming], "excluded_low_hypes": excluded,
            "truncated": {"recent": max(0, len(recent) - cap_recent), "upcoming": max(0, len(upcoming) - cap_upcoming)}}


def _release_marker(game: dict[str, Any], igdb_id: str, recent: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Repère de sortie d'un jeu : par ``igdb_id`` d'abord, sinon par clé normalisée ; sorties récentes seulement."""
    match = next((e for e in recent if igdb_id and e["igdb_id"] == igdb_id), None) \
        or next((e for e in recent if e["key"] == game["key"]), None)
    if match is None:
        return None
    return {"igdb_id": match["igdb_id"], "name": match["name"], "date": match["date"],
            "days_since": -match["days"], "hypes": match["hypes"]}


# --------------------------------------------------------------------------
# Collecte
# --------------------------------------------------------------------------


def _run_source(source: str, collectors: dict[str, Collector], table: dict[str, object]) -> dict[str, Any]:
    """Résultat brut d'un collecteur ; lève ``VeilleError`` (clé absente) ou l'erreur du collecteur."""
    for key in _REQUIRED_KEYS[source]:
        if not str(table[key]).strip():
            raise VeilleError(f"{key} absente : à saisir dans Réglages › Veille")
    if source not in collectors:
        raise VeilleError(f"aucun collecteur fourni pour la source {source}")
    return collectors[source](table)


def _to_candidate(source: str, vod: dict[str, Any]) -> dict[str, Any]:
    game_name = vod.get("game_name")
    return {
        "id": f"{source}:{vod['video_id']}", "source": source, "video_id": vod["video_id"],
        "url": vod["url"], "title": vod.get("title"), "channel_name": vod.get("channel_name"),
        "game_key": normalize(game_name) if game_name else None, "game_name": game_name,
        "duration_s": vod["duration_s"], "published_at": vod["published_at"],
        "view_count": vod.get("view_count"), "thumbnail_url": vod.get("thumbnail_url"), "views_per_hour": vod.get("views_per_hour"),
        "signals": {}, "access_unverified": None, "game_source": None,
        "tags": [str(t) for t in vod.get("tags") or []],
    }


def _deduce_game(candidate: dict[str, Any], known: dict[str, str], min_chars: int) -> None:
    """Jeu d'une VOD YouTube sans jeu : un nom de jeu connu du jour présent en mot(s) entier(s) dans le titre
    ou les tags. Plusieurs trouvés : le plus long gagne s'il contient tous les autres, sinon ambiguïté = aucun jeu.
    Aucun appel LLM, aucun nom inventé."""
    text = f" {' '.join(normalize(t) for t in [candidate.get('title') or '', *candidate['tags']])} "
    found = [key for key in known if len(key) >= min_chars and f" {key} " in text]
    if not found:
        return
    best = max(found, key=len)
    if any(f" {key} " not in f" {best} " for key in found):
        return
    candidate["game_key"], candidate["game_name"], candidate["game_source"] = best, known[best], "titre"


def _check_twitch_access(
    candidates: list[dict[str, Any]], table: dict[str, object], access_check: Callable[[str, float], None],
) -> tuple[list[dict[str, Any]], int]:
    """Teste l'accès des VOD Twitch (les plus vues d'abord, au plus ``twitch_access_check_max``).
    Réservée aux abonnés : écartée et comptée. Autre erreur ou au-delà du plafond : gardée, marquée
    ``access_unverified`` avec la raison (jamais écartée ni validée en silence). Rend (gardées, écartées)."""
    twitch = [c for c in candidates if c["source"] == "twitch"]
    twitch.sort(key=lambda c: -(c["view_count"] or 0))  # tri stable : à vues égales, ordre de la source
    cap = int(table["twitch_access_check_max"])
    timeout_s = float(table["http_timeout_s"])
    dropped: set[str] = set()
    for rank, candidate in enumerate(twitch):
        if rank >= cap:
            candidate["access_unverified"] = f"au-delà du plafond de {cap} VOD testées (twitch_access_check_max)"
            continue
        try:
            access_check(candidate["url"], timeout_s)
        except veille_sources.AccessRestricted:
            dropped.add(candidate["id"])
        except Exception as exc:  # réseau, connexion fermée, délai : ni écartée ni validée
            candidate["access_unverified"] = f"{type(exc).__name__} : {exc}"[:300]
            log.warning("veille twitch : accès de %s non vérifié (%s)", candidate["url"], candidate["access_unverified"])
    return [c for c in candidates if c["id"] not in dropped], len(dropped)


def _parse_published(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"date sans fuseau : {value!r}")
    return parsed


def collect(
    now: datetime,
    *,
    collectors: dict[str, Collector] | None = None,
    config: Config | None = None,
    finalize: bool = True,
    access_check: Callable[[str, float], None] | None = None,
) -> dict[str, Any]:
    """Un relevé (SPEC-bdd9 R2, R4, R5) : appelle les collecteurs injectés, écrit
    ``history/<date>.json`` et ``days/<date>.json`` et rend l'état du jour.
    Une source en erreur n'arrête pas les autres ; seuls un réglage invalide
    ou un fichier d'état illisible lèvent ``VeilleError``. ``finalize=False`` laisse
    ``finished_at`` à ``null`` (le choix de Claude suit, voir ``run_if_due``).
    ``access_check(url, timeout_s)`` teste l'accès des VOD Twitch (défaut :
    ``veille_sources.check_twitch_access``, yt-dlp sans téléchargement) : voir ``_check_twitch_access``."""
    config = config or load_config()
    collectors = veille_sources.default_collectors() if collectors is None else collectors
    table = settings(config)
    sdir = _state_dir(table)
    local_now = now.astimezone(ZoneInfo(str(table["timezone"])))
    today = local_now.date()
    day = today.isoformat()
    started_at = now.isoformat()

    previous = [p for p in _load_history(sdir, today, int(table["baseline_days"]))]
    known = _seen_video_ids(sdir) | _queue_video_ids(config)
    workspace = Path(config.workspace_dir)

    sources: dict[str, dict[str, Any]] = {}
    twitch_hist: dict[str, dict[str, Any]] = {}
    steam_hist: dict[str, dict[str, Any]] = {}
    sellers_hist: dict[str, dict[str, Any]] = {}
    youtube_hist: dict[str, dict[str, Any]] = {}
    twitch_igdb: dict[str, str] = {}  # clé de jeu -> igdb_id fourni par Twitch (hors historique)
    igdb_games: list[dict[str, Any]] = []
    igdb_skipped = 0
    raw_vods: list[tuple[str, dict[str, Any]]] = []

    for source in SOURCES:
        status: dict[str, Any] = {"status": "ok", "at": now.isoformat(), "error": None, "counts": {}}
        try:
            result = _run_source(source, collectors, table)
            if source == "twitch":
                for game in result["games"]:
                    twitch_hist[normalize(game["name"])] = {"name": game["name"], "viewers_fr": game["viewers_fr"]}
                    twitch_igdb[normalize(game["name"])] = str(game.get("igdb_id") or "")
                vods = list(result["vods"])
                status["counts"] = {"games": len(twitch_hist), "vods": len(vods), "private": int(result.get("private_vods", 0))}
            elif source == "youtube":
                vods = list(result["videos"])
                for vod in vods:
                    if vod.get("game_name") and vod.get("views_per_hour") is not None:
                        entry = youtube_hist.setdefault(normalize(vod["game_name"]), {"views_per_hour_sum": 0})
                        entry["views_per_hour_sum"] += vod["views_per_hour"]
                status["counts"] = {"videos": len(vods)}
            elif source == "igdb":
                igdb_games = list(result["games"])
                igdb_skipped = int(result.get("skipped_rows", 0))
                vods = []
            elif source == "steam_fr":
                for game in result["games"]:
                    sellers_hist[str(game["appid"])] = {"name": game["name"], "rank": game["rank"],
                                                        "last_week_rank": game.get("last_week_rank")}
                vods = []
                status["counts"] = {"games": len(sellers_hist)}
            else:
                for game in result["games"]:
                    steam_hist[str(game["appid"])] = {"name": game["name"], "players": game["players"],
                                                      "rank": game.get("rank"), "last_week_rank": game.get("last_week_rank")}
                vods = []
                status["counts"] = {"games": len(steam_hist)}
                if result.get("unnamed"):
                    status["unnamed"] = list(result["unnamed"])
                    log.warning("veille steam : %d jeu(x) sans nom, ex. %s", len(status["unnamed"]), status["unnamed"][0]["reason"])
            for vod in vods:
                _parse_published(vod["published_at"])
                vod["video_id"], vod["url"], vod["duration_s"]  # champs obligatoires
            raw_vods.extend((source, vod) for vod in vods)
        except Exception as exc:  # une source en erreur ne bloque pas les autres, jamais avalée
            status.update(status="error", error=f"{type(exc).__name__} : {exc}" if not isinstance(exc, (VeilleError, veille_sources.SourceError)) else str(exc), counts={})
            if source == "twitch":
                twitch_hist, twitch_igdb = {}, {}
            elif source == "igdb":
                igdb_games, igdb_skipped = [], 0
            elif source == "steam":
                steam_hist = {}
            elif source == "steam_fr":
                sellers_hist = {}
            else:
                youtube_hist = {}
            raw_vods = [(s, v) for s, v in raw_vods if s != source]
        sources[source] = status

    # Candidats (R5)
    excluded = {"too_short": 0, "too_old": 0, "already_known": 0}
    candidates: list[dict[str, Any]] = []
    max_age = timedelta(hours=float(table["vod_max_age_h"]))
    for source, vod in raw_vods:
        min_duration = table["youtube_min_duration_s" if source == "youtube" else "vod_min_duration_s"]
        if vod["duration_s"] < min_duration:
            excluded["too_short"] += 1
        elif now - _parse_published(vod["published_at"]) > max_age:
            excluded["too_old"] += 1
        elif vod["video_id"] in known or (workspace / vod["video_id"]).exists():
            excluded["already_known"] += 1
        else:
            candidates.append(_to_candidate(source, vod))

    known_games: dict[str, str] = {k: g["name"] for k, g in twitch_hist.items()}
    for entry in (*steam_hist.values(), *sellers_hist.values()):
        known_games.setdefault(normalize(entry["name"]), entry["name"])
    in_window = _classify_releases(igdb_games, today, table)
    for entry in in_window:
        if entry["hypes"] >= int(table["igdb_min_hypes"]):  # type: ignore[call-overload]
            known_games.setdefault(entry["key"], entry["name"])
    for candidate in candidates:
        if candidate["source"] == "youtube" and not candidate["game_key"]:
            _deduce_game(candidate, known_games, int(table["youtube_game_min_chars"]))  # type: ignore[call-overload]

    if sources["twitch"]["status"] == "ok":
        candidates, restricted = _check_twitch_access(candidates, table, access_check or veille_sources.check_twitch_access)
        sources["twitch"]["counts"]["restricted"] = restricted
    vod_counts: dict[str, int] = {}
    for candidate in candidates:
        if candidate["game_key"]:
            vod_counts[candidate["game_key"]] = vod_counts.get(candidate["game_key"], 0) + 1

    games = _build_games(twitch_hist, steam_hist, youtube_hist, vod_counts, previous, table, sellers_hist)
    releases = _group_releases(in_window, games, twitch_igdb, table)
    if sources["igdb"]["status"] == "ok":
        sources["igdb"]["counts"] = {"rows": len(igdb_games), "recent": len(releases["recent"]),
                                     "upcoming": len(releases["upcoming"]), "skipped_rows": igdb_skipped}
    for game in games:
        game["release"] = _release_marker(game, twitch_igdb.get(game["key"], ""), releases["recent"])
    by_key = {g["key"]: g for g in games}
    for candidate in candidates:
        game = by_key.get(candidate["game_key"])
        release = game["release"] if game else (
            _release_marker({"key": candidate["game_key"]}, "", releases["recent"]) if candidate["game_key"] else None)
        candidate["signals"] = {"release_days_since": release["days_since"] if release else None}
        if game:
            candidate["signals"] |= {"twitch_delta_pct": game["twitch_delta_pct"], "steam_delta_pct": game["steam_delta_pct"],
                                    "steam_rank_gain": game["steam_rank_gain"], "steam_new_in_top": game["steam_new_in_top"],
                                    "steam_sellers_gain": game["steam_sellers_gain"], "steam_sellers_new": game["steam_sellers_new"]}

    _write(sdir / "history" / f"{day}.json", {
        "date": day, "at": now.isoformat(), "twitch": twitch_hist, "steam": steam_hist, "steam_fr": sellers_hist, "youtube": youtube_hist,
    })
    state = {
        "date": day, "started_at": started_at, "finished_at": now.isoformat() if finalize else None, "sources": sources,
        "games": games, "candidates": candidates, "excluded": excluded, "releases": releases,
        "llm": {"status": "skipped", "error": None, "model": None},
        "proposals": [], "skipped_note": "", "refresh_requested_at": None,
    }
    _write(sdir / "days" / f"{day}.json", state)
    _prune_history(sdir, today, int(table["history_days"]))
    return state


# --------------------------------------------------------------------------
# Choix de Claude (R6)
# --------------------------------------------------------------------------

_DECIDED = ("queued", "ignored")


def _schema(max_picks: int) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["picks", "skipped_note"],
        "additionalProperties": False,
        "properties": {
            "picks": {
                "type": "array", "maxItems": max_picks,
                "items": {
                    "type": "object", "required": ["candidate_id", "reason"], "additionalProperties": False,
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "reason": {"type": "string", "minLength": 1, "maxLength": 240},
                    },
                },
            },
            "skipped_note": {"type": "string", "maxLength": 300},
        },
    }


def _check_picks(candidate_ids: set[str]) -> Callable[[Any], None]:
    def check(value: Any) -> None:
        seen: set[str] = set()
        for pick in value["picks"]:
            cid = pick["candidate_id"]
            if cid not in candidate_ids:
                raise llm.SchemaError(f"candidate_id inconnu : {cid!r}")
            if cid in seen:
                raise llm.SchemaError(f"candidate_id en double : {cid!r}")
            seen.add(cid)

    return check


def _fmt(value: Any) -> str:
    return "inconnu" if value is None else str(value)


def _release_line(entry: dict[str, Any], *, upcoming: bool) -> str:
    when = f"{entry['date']} J-{entry['days']}" if upcoming else f"J+{-entry['days']}"
    portage = " portage=oui" if entry.get("portage") else ""
    return (f"- {entry['name']} : {when} hypes={_fmt(entry.get('hypes'))} "
            f"plateformes={', '.join(entry.get('platforms') or [])}{portage}")


def _releases_block(day_state: dict[str, Any], table: dict[str, object]) -> list[str]:
    """Bloc « Sorties de jeux (IGDB) » du prompt (R15) ; source en erreur : indisponible avec l'erreur."""
    igdb = (day_state.get("sources") or {}).get("igdb")
    if not igdb or igdb.get("status") != "ok":
        reason = igdb["error"] if igdb else "relevé sans source IGDB"
        return ["", f"Sorties de jeux : indisponibles ({reason})"]
    releases = day_state.get("releases") or _empty_releases()
    lines = ["", "Sorties de jeux (IGDB) :", "Sorties récentes :"]
    lines += [_release_line(e, upcoming=False) for e in releases["recent"]] or ["- aucune"]
    lines += ["Sorties à venir :"]
    lines += [_release_line(e, upcoming=True) for e in releases["upcoming"]] or ["- aucune"]
    lines.append(
        f"Un jeu sorti depuis 0 à {table['release_window_days']} jours est dans sa fenêtre de sortie : à qualité de "
        "gameplay égale, propose d'abord ses VOD ; une sortie à venir n'est pas un motif de choix aujourd'hui.")
    return lines


def _prompt(day_state: dict[str, Any], table: dict[str, object]) -> str:
    taste = str(table["taste"]).strip() or "aucune préférence déclarée"
    lines = [
        "Tu choisis, pour un clippeur de streams, les VOD du jour dont tirer des clips courts pour TikTok.",
        f"Goûts de l'utilisateur : {taste}",
        f"Nombre maximum de VOD à proposer : {table['max_vods_per_day']} (zéro est une réponse valide).",
        "Choisis les VOD dont le gameplay se prête à des clips courts compréhensibles seuls ET qui collent aux "
        "goûts, en privilégiant ce qui monte, sans juger les personnes. Une donnée inconnue est inconnue : "
        "ne l'invente pas.",
        "",
        "Jeux (viewers Twitch FR, joueurs Steam, variation vs moyenne des jours précédents, gain de rang Steam vs semaine dernière, rang et gain dans le top des ventes Steam du pays) :",
    ]
    for game in day_state["games"]:
        lines.append(
            f"- {game['name']} : twitch_fr_viewers={_fmt(game['twitch_fr_viewers'])} "
            f"hors_twitch_fr={game.get('twitch_match') is False} "
            f"twitch_delta_pct={_fmt(game['twitch_delta_pct'])} steam_players={_fmt(game.get('steam_players'))} "
            f"steam_delta_pct={_fmt(game['steam_delta_pct'])} "
            f"steam_rank_gain_vs_last_week={_fmt(game.get('steam_rank_gain'))} "
            f"steam_new_in_top={_fmt(game.get('steam_new_in_top'))} "
            f"ventes_fr_rang={_fmt(game.get('steam_sellers_rank'))} "
            f"ventes_fr_gain_vs_semaine_derniere={_fmt(game.get('steam_sellers_gain'))} "
            f"ventes_fr_nouveau={_fmt(game.get('steam_sellers_new'))} "
            f"youtube_views_per_hour={_fmt(game.get('youtube_views_per_hour'))} vod_count={_fmt(game.get('vod_count'))} "
            f"sortie_j_plus={_fmt((game.get('release') or {}).get('days_since'))} "
            f"hypes_igdb={_fmt((game.get('release') or {}).get('hypes'))}")
    lines += _releases_block(day_state, table)
    lines += ["", "Candidats (VOD) :"]
    for c in day_state["candidates"]:
        signals = c.get("signals") or {}
        lines.append(
            f"- id={c['id']} source={c['source']} titre={c.get('title')!r} chaîne={c.get('channel_name')!r} "
            f"jeu={_fmt(c.get('game_name'))}{' (déduit du titre)' if c.get('game_source') == 'titre' else ''} durée_s={c['duration_s']} publiée={c['published_at']} "
            f"vues={_fmt(c.get('view_count'))} vues_par_heure={_fmt(c.get('views_per_hour'))} "
            f"twitch_delta_pct={_fmt(signals.get('twitch_delta_pct'))} "
            f"steam_delta_pct={_fmt(signals.get('steam_delta_pct'))} "
            f"steam_rank_gain_vs_last_week={_fmt(signals.get('steam_rank_gain'))} "
            f"steam_new_in_top={_fmt(signals.get('steam_new_in_top'))} "
            f"ventes_fr_gain_vs_semaine_derniere={_fmt(signals.get('steam_sellers_gain'))} "
            f"ventes_fr_nouveau={_fmt(signals.get('steam_sellers_new'))} "
            f"sortie_j_plus={_fmt(signals.get('release_days_since'))}")
    return "\n".join(lines)


def decide(day_state: dict[str, Any], config: Config) -> dict[str, Any]:
    """Un seul appel texte à ``llm.ask("veille", ...)`` (R6) ; rend une copie de l'état avec ``llm``,
    ``proposals`` et ``skipped_note``. Aucun candidat : ``skipped``, Claude n'est pas appelé. Réponse
    refusée (ou erreur du backend) : ``llm.status = "error"`` avec le message, aucune proposition.
    Chaque proposition porte un instantané de son candidat (``candidate``) : l'écran l'affiche encore
    une fois la VOD mise en file, quand elle n'est plus candidate."""
    table = settings(config)
    state = {**day_state}
    candidates = state["candidates"]
    model = config.section("llm")["usages"].get("veille", {}).get("model")
    if not candidates:
        state.update(llm={"status": "skipped", "error": None, "model": None}, proposals=[], skipped_note="")
        return state
    try:
        answer = llm.ask("veille", _prompt(state, table), [], _schema(int(table["max_vods_per_day"])),
                         config=config, check=_check_picks({c["id"] for c in candidates}))
    except llm.LLMError as exc:
        log.error("veille : choix de Claude refusé : %s", exc)
        state.update(llm={"status": "error", "error": str(exc), "model": model}, proposals=[], skipped_note="")
        return state
    by_id = {c["id"]: c for c in candidates}
    state["proposals"] = [
        {"candidate_id": pick["candidate_id"], "rank": rank, "reason": pick["reason"], "status": "proposed",
         "decided_at": None, "channel": None, "queue_entry_id": None, "candidate": by_id[pick["candidate_id"]]}
        for rank, pick in enumerate(answer["picks"], start=1)]
    state.update(llm={"status": "ok", "error": None, "model": model}, skipped_note=answer["skipped_note"])
    return state


# --------------------------------------------------------------------------
# Exécution par le worker (R7)
# --------------------------------------------------------------------------


def _day_path(sdir: Path, day: str) -> Path:
    return sdir / "days" / f"{day}.json"


def _state_lock(sdir: Path) -> Path:
    return sdir / "state"


def _read_day(sdir: Path, day: str) -> dict[str, Any] | None:
    return _read_json(_day_path(sdir, day), None)


def _due(now: datetime, table: dict[str, object], sdir: Path) -> bool:
    if (sdir / "refresh.json").exists():
        return True
    local = now.astimezone(ZoneInfo(str(table["timezone"])))
    hour, minute = str(table["run_at"]).split(":")
    if (local.hour, local.minute) < (int(hour), int(minute)):
        return False
    day = _read_day(sdir, local.date().isoformat())
    return day is None or day.get("finished_at") is None  # un relevé interrompu est repris


def run_if_due(
    now: datetime,
    config: Config,
    collectors: dict[str, Collector] | None = None,
) -> dict[str, Any] | None:
    """Relevé + choix de Claude si dû (R7) ; rend l'état du jour, ``None`` si rien n'était dû.
    ``enabled`` faux : rien n'est lu ni écrit. ``refresh.json`` est consommé avant de commencer ;
    les propositions déjà ``queued``/``ignored`` survivent à un relevé rejoué."""
    if not config.section("veille").get("enabled"):
        return None
    table = settings(config)
    sdir = _state_dir(table)
    if not _due(now, table, sdir):
        return None
    day = now.astimezone(ZoneInfo(str(table["timezone"]))).date().isoformat()
    refresh = _read_json(sdir / "refresh.json", None)
    (sdir / "refresh.json").unlink(missing_ok=True)
    requested_at = refresh.get("requested_at") if isinstance(refresh, dict) else None
    skeleton = _read_day(sdir, day) or {
        "date": day, "sources": {}, "games": [], "candidates": [], "excluded": {},
        "llm": {"status": "skipped", "error": None, "model": None}, "proposals": [], "skipped_note": ""}
    skeleton.update(started_at=now.isoformat(), finished_at=None, refresh_requested_at=requested_at)
    _write(_day_path(sdir, day), skeleton)  # l'écran voit « en cours » dès maintenant
    decided = [p for p in skeleton["proposals"] if p["status"] in _DECIDED]

    state = collect(now, collectors=collectors, config=config, finalize=False)
    state["refresh_requested_at"] = requested_at
    state = decide(state, config)
    state["finished_at"] = now.isoformat()
    with channel_mod.file_lock(_state_lock(sdir)):
        ids = {p["candidate_id"] for p in decided}
        state["proposals"] = decided + [p for p in state["proposals"] if p["candidate_id"] not in ids]
        _write(_day_path(sdir, day), state)
    return state


def _update_proposal(
    config: Config, day: str, candidate_id: str,
    update: Callable[[dict[str, Any], dict[str, Any]], None],
) -> None:
    """Relit le jour sous verrou, applique ``update(proposition, seen)``, réécrit les deux fichiers."""
    sdir = _state_dir(settings(config))
    with channel_mod.file_lock(_state_lock(sdir)):
        state = _read_day(sdir, day)
        if state is None:
            raise VeilleError(f"aucun relevé de veille pour le {day}")
        proposal = next((p for p in state["proposals"] if p["candidate_id"] == candidate_id), None)
        if proposal is None:
            raise VeilleError(f"candidat inconnu : {candidate_id} (relevé du {day})")
        if proposal["status"] != "proposed":
            raise VeilleError(f"candidat déjà traité : {candidate_id} ({proposal['status']})")
        seen = _read_json(sdir / "seen.json", {"queued": [], "ignored": []})
        update(proposal, seen)
        _write(sdir / "seen.json", seen)
        _write(_day_path(sdir, day), state)


def clip(
    day: str,
    candidate_id: str,
    channel: str | None,
    short_clips: bool | None = None,
    config: Config | None = None,
) -> dict[str, Any]:
    """Met la VOD proposée en file (``worker.enqueue``) ; rend l'entrée de file (R7)."""
    from clipper import worker  # import local : worker importe veille dans sa boucle

    config = config or load_config()
    result: dict[str, Any] = {}

    def update(proposal: dict[str, Any], seen: dict[str, Any]) -> None:
        candidate = proposal["candidate"]
        try:
            entry = worker.enqueue(candidate["url"], channel, "run", short_clips=short_clips, config=config)
        except worker.WorkerError as exc:
            raise VeilleError(f"mise en file impossible pour {candidate_id} : {exc}") from exc
        at = datetime.now(timezone.utc).isoformat()
        proposal.update(status="queued", decided_at=at, channel=channel, queue_entry_id=entry["id"])
        seen["queued"].append({"candidate_id": candidate_id, "video_id": entry["video_id"], "url": candidate["url"],
                               "date": day, "channel": channel, "queue_entry_id": entry["id"], "at": at})
        result.update(entry)

    _update_proposal(config, day, candidate_id, update)
    return result


def ignore(day: str, candidate_id: str, config: Config | None = None) -> None:
    """Marque la proposition ignorée ; son ``video_id`` n'est plus jamais candidat (R7)."""
    config = config or load_config()

    def update(proposal: dict[str, Any], seen: dict[str, Any]) -> None:
        at = datetime.now(timezone.utc).isoformat()
        proposal.update(status="ignored", decided_at=at)
        seen["ignored"].append({"candidate_id": candidate_id, "video_id": proposal["candidate"]["video_id"],
                                "date": day, "at": at})

    _update_proposal(config, day, candidate_id, update)


# --------------------------------------------------------------------------
# Meilleurs clips du jour (R7) : archivage réversible, output/ jamais touché
# --------------------------------------------------------------------------

_KEEP_PUBLISH_STATUSES = ("approved", "scheduled", "published")


def _selection_path(sdir: Path, day: str) -> Path:
    return sdir / "selection" / f"{day}.json"


def _series_key(clip_id: str, sidecar: dict[str, Any]) -> str:
    """Base commune des parties d'une série (même règle que clipper.publish), sinon le clip lui-même."""
    if sidecar.get("part") is not None and (sidecar.get("parts_total") or 1) > 1 and "-p" in clip_id:
        return clip_id.rsplit("-p", 1)[0]
    return clip_id


def _protected_clips(config: Config) -> set[tuple[str, str]]:
    """Clips dont l'entrée de publication est approuvée, programmée ou publiée (jamais archivés)."""
    folder = Path(str(config.section("publish")["state_dir"]))
    names = sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []
    try:
        return {(e["video_id"], e["clip_id"]) for name in names
                for e in publish.list_entries(name, state_dir=folder) if e["status"] in _KEEP_PUBLISH_STATUSES}
    except (publish.PublishError, ValueError) as exc:
        raise VeilleError(f"file de publication illisible : {exc}") from exc


def _video_clips(config: Config, video_id: str) -> list[dict[str, Any]]:
    folder = Path(config.output_dir) / video_id
    clips = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            sidecar = publish.read_sidecar(config.output_dir, video_id, path.stem)
            clips.append({"video_id": video_id, "clip_id": path.stem, "qa": sidecar["qa"]["status"],
                          "score": sidecar["score"], "series": _series_key(path.stem, sidecar)})
        except (publish.PublishError, ValueError, KeyError, TypeError) as exc:
            raise VeilleError(f"sidecar de clip illisible : {path} ({exc})") from exc
    return clips


def _finished_day(config: Config, video_id: str, tz: ZoneInfo) -> str | None:
    state = _read_json(Path(config.workspace_dir) / video_id / "pipeline.json", None)
    if not state or state.get("status") != "done" or not state.get("updated_at"):
        return None
    return datetime.fromisoformat(state["updated_at"]).astimezone(tz).date().isoformat()


def select_best(now: datetime, config: Config) -> None:
    """Recalcule ``selection/<jour>.json`` pour chaque jour où une VOD de la veille s'est terminée (R7)."""
    table = settings(config)
    sdir = _state_dir(table)
    tz = ZoneInfo(str(table["timezone"]))
    seen = _read_json(sdir / "seen.json", {"queued": [], "ignored": []})
    videos_by_day: dict[str, list[str]] = {}
    for entry in seen.get("queued", []):
        day = _finished_day(config, entry["video_id"], tz)
        if day and entry["video_id"] not in videos_by_day.setdefault(day, []):
            videos_by_day[day].append(entry["video_id"])
    if not videos_by_day:
        return
    protected = _protected_clips(config)
    best = int(table["best_clips_per_day"])
    for day, video_ids in sorted(videos_by_day.items()):
        units: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for video_id in video_ids:
            for item in _video_clips(config, video_id):
                units.setdefault((video_id, item["series"]), []).append(item)
        # une série compte pour un, au score de la série ; une partie rejetée écarte toute la série
        ranked = sorted(
            ((max(i["score"] for i in items), key, items) for key, items in units.items()
             if all(i["qa"] == "passed" for i in items)),
            key=lambda u: (-u[0], u[1]))
        with channel_mod.file_lock(_state_lock(sdir)):
            restored = (_read_json(_selection_path(sdir, day), {}) or {}).get("restored", [])
            restored_ids = {(r["video_id"], r["clip_id"]) for r in restored}
            kept: list[dict[str, Any]] = []
            archived: list[dict[str, Any]] = []
            for rank, (score, _key, items) in enumerate(ranked, start=1):
                rows = [{"video_id": i["video_id"], "clip_id": i["clip_id"], "score": score, "rank": rank}
                        for i in items]
                if rank <= best or any((i["video_id"], i["clip_id"]) in protected for i in items):
                    kept.extend(rows)
                else:
                    archived.extend(r for r in rows if (r["video_id"], r["clip_id"]) not in restored_ids)
            _write(_selection_path(sdir, day), {
                "date": day, "computed_at": now.isoformat(), "kept": kept, "archived": archived,
                "restored": restored})


def restore(video_id: str, clip_id: str, config: Config | None = None) -> None:
    """Sort un clip de ``archived`` et le met dans ``restored`` : il reste visible aux recalculs suivants (R7)."""
    config = config or load_config()
    sdir = _state_dir(settings(config))
    folder = sdir / "selection"
    with channel_mod.file_lock(_state_lock(sdir)):
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            selection = _read_json(path, {})
            match = [a for a in selection.get("archived", []) if a["video_id"] == video_id and a["clip_id"] == clip_id]
            if match:
                selection["archived"] = [a for a in selection["archived"] if a not in match]
                selection.setdefault("restored", []).append({
                    "video_id": video_id, "clip_id": clip_id, "restored_at": datetime.now(timezone.utc).isoformat()})
                _write(path, selection)
                return
    raise VeilleError(f"clip non archivé par la veille : {video_id}/{clip_id}")
