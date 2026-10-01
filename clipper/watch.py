"""Surveillance des VOD d'une chaine (SPEC-74e9 §5, ADR-35b7 §1 et §3).

Bibliotheque, pas une etape (ADR-b16b) : elle liste les VOD de
``[channel].source_url`` par yt-dlp en extraction plate (aucun
telechargement, le telechargement reste l'etape ``download`` lancee via la
file) et ecrit ``state/watch/<chaine>.json`` :

    {checked_at, seen: [video_id...], pending: [{video_id, url, title,
     duration_s, published_at, found_at}], last_error | null}

Une VOD nouvelle part en file (mode ``auto``, ajoutee a ``seen``) ou en
``pending`` (mode ``review``, « a confirmer » sur le tableau de bord).
Le listeur est injecte (``lister(source_url) -> [vod]``) : le defaut est
``list_vods`` (yt-dlp), aucun test n'appelle le reseau.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from clipper import channel as channel_mod
from clipper import worker
from clipper.config import Config, load_config

CONFIG_DEFAULTS: dict[str, object] = {
    "state_dir": "state/watch",
    "presets_dir": "presets",
    "base_config": "config.toml",
    "socket_timeout_s": 30,
}

Lister = Callable[[str], list[dict[str, Any]]]


class WatchError(Exception):
    """Surveillance impossible en l'etat : chaine sans source, VOD inconnue,
    fichier d'etat illisible, entree de listage inexploitable."""


# --------------------------------------------------------------------------
# Listeur reel (yt-dlp, extraction plate)
# --------------------------------------------------------------------------

_NOT_A_VOD = ("is_live", "is_upcoming")


def _flatten(info: dict[str, Any]) -> list[dict[str, Any]]:
    entries = info.get("entries")
    if entries is None:
        return [info]
    flat: list[dict[str, Any]] = []
    for entry in entries:
        if entry:
            flat.extend(_flatten(entry))
    return flat


def _published_at(entry: dict[str, Any]) -> str | None:
    timestamp = entry.get("timestamp")
    if timestamp:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    upload_date = entry.get("upload_date")
    if upload_date:
        try:
            return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
        except ValueError as exc:
            raise WatchError(f"date de publication illisible pour {entry.get('id')!r} : {upload_date!r}") from exc
    return None


def list_vods(
    source_url: str,
    *,
    ydl_factory: Callable[[dict[str, Any]], Any] = yt_dlp.YoutubeDL,
    socket_timeout_s: float = float(CONFIG_DEFAULTS["socket_timeout_s"]),
) -> list[dict[str, Any]]:
    """VOD de ``source_url`` (page chaine YouTube ou Twitch) : extraction plate,
    rien n'est telecharge. Un direct en cours ou programme n'est pas encore une
    VOD et n'est pas rendu ; ``duration_s`` vaut None quand yt-dlp ne la donne
    pas (``check`` re-evaluera la VOD au passage suivant)."""
    opts = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": socket_timeout_s,
    }
    with ydl_factory(opts) as ydl:
        info = ydl.extract_info(source_url, download=False)

    vods: list[dict[str, Any]] = []
    for entry in _flatten(info):
        if entry.get("live_status") in _NOT_A_VOD:
            continue
        video_id = entry.get("id")
        url = entry.get("url") or entry.get("webpage_url")
        if not video_id or not url:
            raise WatchError(f"entree de listage sans id ou sans url pour {source_url!r} : {entry.get('id')!r}")
        duration = entry.get("duration")
        vods.append({
            "video_id": video_id,
            "url": url,
            "title": entry.get("title"),
            "duration_s": int(duration) if duration is not None else None,
            "published_at": _published_at(entry),
        })
    return vods


def _default_lister() -> Lister:
    """Le listeur par defaut est ``list_vods`` (resolu a l'appel)."""
    return list_vods


# --------------------------------------------------------------------------
# Etat state/watch/<chaine>.json
# --------------------------------------------------------------------------


def _state_path(channel: str, config: Config) -> Path:
    return Path(config.section("watch")["state_dir"]) / f"{channel}.json"


def _empty_state() -> dict[str, Any]:
    return {"checked_at": None, "seen": [], "pending": [], "last_error": None}


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not all(key in state for key in ("checked_at", "seen", "pending", "last_error")):
            raise KeyError("champs checked_at/seen/pending/last_error attendus")
    except (ValueError, KeyError, TypeError) as exc:
        raise WatchError(f"etat de surveillance illisible : {path.name} ({exc})") from exc
    return state


def _write_state(path: Path, state: dict[str, Any]) -> None:
    channel_mod.atomic_write_json(path, state)


def _mark_seen(state: dict[str, Any], video_id: str) -> None:
    if video_id not in state["seen"]:
        state["seen"].append(video_id)


def _queue_vod(url: str, channel: str, config: Config) -> None:
    """Met la VOD en file ; une VOD deja ``waiting`` (SPEC-74e9 §2.2) est deja
    prise en compte, pas une erreur."""
    try:
        worker.enqueue(url, channel, "run", config=config)
    except worker.WorkerError:
        pass


def _channel_settings(channel: str, config: Config) -> dict[str, object]:
    section = config.section("watch")
    _merged, settings = channel_mod.load_channel(
        channel, presets_dir=section["presets_dir"], base=section["base_config"])
    return settings


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def check(
    channel: str,
    now: datetime,
    *,
    lister: Lister | None = None,
    config: Config | None = None,
) -> None:
    """Un passage de surveillance pour ``channel`` (SPEC-74e9 §5.1-5.4) : liste
    les VOD de sa ``source_url``, ignore celles plus courtes que
    ``watch_min_duration_s`` et celles deja vues ou en attente, puis met les
    nouvelles en file (mode ``auto``) ou en ``pending`` (mode ``review``).
    Une erreur du listeur est ecrite dans ``last_error``, ``seen`` et
    ``pending`` restent intacts, la chaine reste surveillee."""
    config = config or load_config()
    settings = _channel_settings(channel, config)
    source_url = str(settings["source_url"])
    if not source_url:
        raise WatchError(f"chaine {channel!r} : source_url vide, rien a surveiller")
    min_duration = int(settings["watch_min_duration_s"])
    mode = settings["mode"]
    lister = lister or _default_lister()
    path = _state_path(channel, config)

    try:
        vods = lister(source_url)
    except Exception as exc:  # reseau, yt-dlp : journalise dans l'etat, jamais avale
        with channel_mod.file_lock(path):
            state = _read_state(path)
            state.update(checked_at=now.isoformat(), last_error=f"{type(exc).__name__} : {exc}")
            _write_state(path, state)
        return

    with channel_mod.file_lock(path):
        state = _read_state(path)
        state.update(checked_at=now.isoformat(), last_error=None)
        try:
            for vod in vods:
                video_id = vod["video_id"]
                if vod.get("duration_s") is None or vod["duration_s"] < min_duration:
                    continue
                if video_id in state["seen"] or any(p["video_id"] == video_id for p in state["pending"]):
                    continue
                if mode == "auto":
                    _queue_vod(vod["url"], channel, config)
                    _mark_seen(state, video_id)
                else:
                    state["pending"].append({
                        "video_id": video_id, "url": vod["url"], "title": vod.get("title"),
                        "duration_s": vod["duration_s"], "published_at": vod.get("published_at"),
                        "found_at": now.isoformat(),
                    })
        except Exception as exc:  # une VOD inexploitable : ce qui est fait est garde, l'erreur est ecrite
            state["last_error"] = f"{type(exc).__name__} : {exc}"
        _write_state(path, state)


def _take_pending(state: dict[str, Any], channel: str, video_id: str) -> dict[str, Any]:
    for vod in state["pending"]:
        if vod["video_id"] == video_id:
            return vod
    raise WatchError(f"VOD {video_id!r} introuvable parmi les VOD a confirmer de {channel!r}")


def confirm(channel: str, video_id: str, *, config: Config | None = None) -> dict[str, Any]:
    """Confirme une VOD ``pending`` : mise en file (action ``run``), retiree de
    ``pending`` et ajoutee a ``seen`` (sinon le prochain ``check`` la
    retrouverait). Retourne l'entree de file."""
    config = config or load_config()
    path = _state_path(channel, config)
    with channel_mod.file_lock(path):
        state = _read_state(path)
        vod = _take_pending(state, channel, video_id)
        try:
            entry = worker.enqueue(vod["url"], channel, "run", config=config)
        except worker.WorkerError:
            entry = None  # deja en attente dans la file
        state["pending"] = [p for p in state["pending"] if p["video_id"] != video_id]
        _mark_seen(state, video_id)
        _write_state(path, state)
    return entry if entry is not None else {"video_id": video_id, "url": vod["url"], "channel": channel,
                                            "action": "run", "status": "waiting"}


def ignore(channel: str, video_id: str, *, config: Config | None = None) -> None:
    """Ignore une VOD ``pending`` : retiree de ``pending``, ajoutee a ``seen``,
    jamais mise en file."""
    config = config or load_config()
    path = _state_path(channel, config)
    with channel_mod.file_lock(path):
        state = _read_state(path)
        _take_pending(state, channel, video_id)
        state["pending"] = [p for p in state["pending"] if p["video_id"] != video_id]
        _mark_seen(state, video_id)
        _write_state(path, state)


def is_due(channel: str, interval_s: float, now: datetime, *, config: Config | None = None) -> bool:
    """Vrai si la chaine n'a jamais ete verifiee ou si ``checked_at +
    interval_s`` est passe (SPEC-74e9 §5.1)."""
    config = config or load_config()
    checked_at = _read_state(_state_path(channel, config))["checked_at"]
    if checked_at is None:
        return True
    try:
        last = datetime.fromisoformat(checked_at)
    except ValueError as exc:
        raise WatchError(f"checked_at illisible pour {channel!r} : {checked_at!r}") from exc
    return (now - last).total_seconds() >= interval_s
