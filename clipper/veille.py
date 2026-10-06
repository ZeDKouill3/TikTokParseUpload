"""Veille des sujets chauds : relevé quotidien (ADR-ca9a, SPEC-bdd9 R1, R2, R4, R5).

Bibliothèque, pas une étape (ADR-b16b) : rien sous ``workspace/<video_id>/``,
aucun import de ``clipper.web`` ni d'une étape. Tout l'état est en JSON sous
``state/veille/`` (écriture atomique sous verrou) :

    history/<date>.json   relevé du jour (viewers Twitch, joueurs Steam, YouTube)
    days/<date>.json      sources, jeux, candidats, exclus, llm, propositions
    seen.json             VOD déjà mises en file ou ignorées

Les collecteurs sont injectés : ``collectors = {"twitch", "youtube", "steam"}``,
chacun un callable ``collector(settings) -> dict`` (``settings`` = la table
``[veille]`` fusionnée). Contrat de retour :

    twitch  {"games": [{"name", "viewers_fr"}],
             "vods":  [VOD]}
    youtube {"videos": [VOD]}
    steam   {"games": [{"appid", "name", "players"}]}

avec ``VOD = {video_id, url, title, channel_name, game_name | None,
duration_s, published_at (ISO 8601), view_count, views_per_hour}``. Un direct
en cours n'est pas une VOD : le collecteur ne le rend pas. Un collecteur qui
lève, ou dont la réponse est inexploitable, met sa source en ``error`` ; les
autres continuent (ADR-ad2e : aucun chiffre inventé, une donnée absente est
``null``). Sans collecteurs injectés, ``clipper.veille_sources`` fournit les réels.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clipper import channel as channel_mod
from clipper import veille_sources
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
    "twitch_client_id": "",
    "twitch_client_secret": "",
    "youtube_api_key": "",
    "state_dir": "state/veille",
    "http_timeout_s": 20,
}

SOURCES = ("twitch", "youtube", "steam")
Collector = Callable[[dict[str, object]], dict[str, Any]]

# Clés exigées par source (steam n'en demande aucune).
_REQUIRED_KEYS = {
    "twitch": ("twitch_client_id", "twitch_client_secret"),
    "youtube": ("youtube_api_key",),
    "steam": (),
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


def _build_games(
    twitch: dict[str, dict[str, Any]],
    steam: dict[str, dict[str, Any]],
    youtube: dict[str, dict[str, Any]],
    vod_counts: dict[str, int],
    previous: list[dict[str, Any]],
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
        games.append({
            "key": key, "name": info["name"],
            "twitch_fr_viewers": info["viewers_fr"], "twitch_avg": twitch_avg, "twitch_delta_pct": twitch_delta,
            "steam_appid": appid, "steam_match": steam_info is not None, "steam_players": steam_players,
            "steam_avg": steam_avg, "steam_delta_pct": steam_delta,
            "youtube_views_per_hour": youtube.get(key, {}).get("views_per_hour_sum"),
            "vod_count": vod_counts.get(key, 0),
            "baseline_days_available": len(previous),
        })
    return games


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
        "view_count": vod.get("view_count"), "views_per_hour": vod.get("views_per_hour"),
        "signals": {},
    }


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
) -> dict[str, Any]:
    """Un relevé (SPEC-bdd9 R2, R4, R5) : appelle les collecteurs injectés, écrit
    ``history/<date>.json`` et ``days/<date>.json`` et rend l'état du jour.
    Une source en erreur n'arrête pas les autres ; seuls un réglage invalide
    ou un fichier d'état illisible lèvent ``VeilleError``."""
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
    youtube_hist: dict[str, dict[str, Any]] = {}
    raw_vods: list[tuple[str, dict[str, Any]]] = []

    for source in SOURCES:
        status: dict[str, Any] = {"status": "ok", "at": now.isoformat(), "error": None, "counts": {}}
        try:
            result = _run_source(source, collectors, table)
            if source == "twitch":
                for game in result["games"]:
                    twitch_hist[normalize(game["name"])] = {"name": game["name"], "viewers_fr": game["viewers_fr"]}
                vods = list(result["vods"])
                status["counts"] = {"games": len(twitch_hist), "vods": len(vods)}
            elif source == "youtube":
                vods = list(result["videos"])
                for vod in vods:
                    if vod.get("game_name") and vod.get("views_per_hour") is not None:
                        entry = youtube_hist.setdefault(normalize(vod["game_name"]), {"views_per_hour_sum": 0})
                        entry["views_per_hour_sum"] += vod["views_per_hour"]
                status["counts"] = {"videos": len(vods)}
            else:
                for game in result["games"]:
                    steam_hist[str(game["appid"])] = {"name": game["name"], "players": game["players"]}
                vods = []
                status["counts"] = {"games": len(steam_hist)}
            for vod in vods:
                _parse_published(vod["published_at"])
                vod["video_id"], vod["url"], vod["duration_s"]  # champs obligatoires
            raw_vods.extend((source, vod) for vod in vods)
        except Exception as exc:  # une source en erreur ne bloque pas les autres, jamais avalée
            status.update(status="error", error=f"{type(exc).__name__} : {exc}" if not isinstance(exc, (VeilleError, veille_sources.SourceError)) else str(exc), counts={})
            if source == "twitch":
                twitch_hist = {}
            elif source == "steam":
                steam_hist = {}
            else:
                youtube_hist = {}
            raw_vods = [(s, v) for s, v in raw_vods if s != source]
        sources[source] = status

    # Candidats (R5)
    excluded = {"too_short": 0, "too_old": 0, "already_known": 0}
    candidates: list[dict[str, Any]] = []
    vod_counts: dict[str, int] = {}
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
            candidate = _to_candidate(source, vod)
            candidates.append(candidate)
            if candidate["game_key"]:
                vod_counts[candidate["game_key"]] = vod_counts.get(candidate["game_key"], 0) + 1

    games = _build_games(twitch_hist, steam_hist, youtube_hist, vod_counts, previous)
    by_key = {g["key"]: g for g in games}
    for candidate in candidates:
        game = by_key.get(candidate["game_key"])
        if game:
            candidate["signals"] = {"twitch_delta_pct": game["twitch_delta_pct"], "steam_delta_pct": game["steam_delta_pct"]}

    _write(sdir / "history" / f"{day}.json", {
        "date": day, "at": now.isoformat(), "twitch": twitch_hist, "steam": steam_hist, "youtube": youtube_hist,
    })
    state = {
        "date": day, "started_at": started_at, "finished_at": now.isoformat(), "sources": sources,
        "games": games, "candidates": candidates, "excluded": excluded,
        "llm": {"status": "skipped", "error": None, "model": None},
        "proposals": [], "skipped_note": "", "refresh_requested_at": None,
    }
    _write(sdir / "days" / f"{day}.json", state)
    _prune_history(sdir, today, int(table["history_days"]))
    return state
