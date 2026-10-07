"""learning.py : boucle d'apprentissage, 1/4 : rattacher apres releve les posts TikTok aux clips Clipper
sans id de post (ADR-c260, SPEC-00db R1).

Bibliotheque (ADR-b16b) : n'importe ni ``clipper.web`` ni une etape ; appelee par le worker. Un post programme
n'a pas d'adresse a la publication : le releve des Publications (SPEC-47e2) le voit ensuite avec son id et sa
legende. Rien n'est devine (ADR-ad2e) : zero ou plusieurs candidats = non relie, raison ecrite dans
``state/learning/links.json``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from clipper import accounts as accounts_mod
from clipper import channel as channel_mod
from clipper import jury_calibration, outcomes, publish, tiktok
from clipper.config import Config

log = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    "state_dir": "state/learning",  # links.json : derniers passages et clips non relies, avec la raison
    "enabled": True,  # false : le worker ne rattache rien
    "link_window_h": 12,  # ecart maximal (heures) entre la date prevue du clip et la date du post releve
    "maturity_days": 3,  # age minimal (jours depuis la publication) d'un releve pour que ses vues comptent
    "window_days": 90,  # fenetre des posts du compte qui servent de reference au rang des vues
    "min_account_posts": 10,  # posts murs a vues > 0 pour qu'un compte entre dans l'apprentissage
}

REASONS = ("none", "ambiguous")


class LearningError(Exception):
    """Etat ou sidecar illisible : jamais ignore, nomme le fichier."""


def _settings(config: Config | None) -> dict[str, Any]:
    settings = dict(config.section("learning")) if config is not None else dict(CONFIG_DEFAULTS)
    window = settings["link_window_h"]
    if isinstance(window, bool) or not isinstance(window, (int, float)) or window <= 0:
        raise LearningError(f"[learning] link_window_h invalide : {window!r} (un nombre d'heures > 0 est attendu)")
    maturity = settings["maturity_days"]
    if isinstance(maturity, bool) or not isinstance(maturity, (int, float)) or maturity < 1:
        raise LearningError(f"[learning] maturity_days invalide : {maturity!r} (un nombre de jours >= 1 est attendu)")
    days = settings["window_days"]
    if isinstance(days, bool) or not isinstance(days, (int, float)) or days <= 0:
        raise LearningError(f"[learning] window_days invalide : {days!r} (un nombre de jours > 0 est attendu)")
    minimum = settings["min_account_posts"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 2:
        raise LearningError(f"[learning] min_account_posts invalide : {minimum!r} (un entier >= 2 est attendu)")
    if not isinstance(settings["enabled"], bool):
        raise LearningError(f"[learning] enabled invalide : {settings['enabled']!r} (true ou false attendu)")
    return settings


def _links_path(settings: dict[str, Any]) -> Path:
    return Path(settings["state_dir"]) / "links.json"


def _read_links(settings: dict[str, Any]) -> dict[str, Any]:
    path = _links_path(settings)
    if not path.exists():
        return {"last_run": {}, "unlinked": [], "counts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("objet JSON attendu")
    except (OSError, ValueError) as exc:
        raise LearningError(f"état du rattachement illisible ({path}) : {exc}") from exc
    return {"last_run": {}, "unlinked": [], "counts": {}, **data}


def _write_links(settings: dict[str, Any], links: dict[str, Any]) -> None:
    channel_mod.atomic_write_json(_links_path(settings), links)


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _wanted_caption(sidecar: dict[str, Any]) -> str:
    return tiktok._squash(" ".join([str(sidecar.get("caption") or ""), *map(str, sidecar.get("hashtags") or [])]))


def _caption_matches(wanted: str, shown: Any) -> bool:
    """Meme regle que ``tiktok.find_post_link`` : l'une commence par l'autre (texte relevé parfois tronqué)."""
    text = tiktok._squash(shown).rstrip("….").rstrip() if isinstance(shown, str) else ""
    return bool(text and wanted and (wanted.startswith(text) or text.startswith(wanted)))


def _read_sidecars(config: Config | None) -> list[tuple[Path, dict[str, Any]]]:
    root = Path(config.output_dir if config is not None else "output")
    found = []
    for path in sorted(root.glob("*/*.json")) if root.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("objet JSON attendu")
        except (OSError, ValueError) as exc:
            raise LearningError(f"sidecar illisible pour rattacher les posts ({path}) : {exc}") from exc
        found.append((path, data))
    return found


def _entry_channel(video_id: str, clip_id: str, config: Config | None) -> str | None:
    """Fichier de publication (= chaine) qui porte l'entree du clip, ``None`` s'il n'y en a pas."""
    folder = Path(config.section("publish")["state_dir"] if config is not None else publish.CONFIG_DEFAULTS["state_dir"])
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LearningError(f"file de publication illisible ({path}) : {exc}") from exc
        if isinstance(entries, list) and any(
                isinstance(e, dict) and e.get("video_id") == video_id and e.get("clip_id") == clip_id for e in entries):
            return path.stem
    return None


def link_posts(account: str, *, config: Config | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Relie les clips du compte sans id de post aux posts du dernier releve : legende (regle de
    ``find_post_link``) et date du post a ``link_window_h`` heures de la date prevue. Un seul candidat : id et
    adresse ecrits dans le sidecar et l'entree de publication ; zero ou plusieurs : rien n'est modifie, la raison
    (``none`` | ``ambiguous``) est ecrite dans links.json. Rend ``{"linked": [...], "unlinked": {raison: n}}``."""
    settings = _settings(config)
    with channel_mod.file_lock(_links_path(settings)):  # plusieurs workers : un seul rattache a la fois
        return _link_posts(account, settings, config, now)


def _link_posts(account: str, settings: dict[str, Any], config: Config | None, now: datetime | None) -> dict[str, Any]:
    window = timedelta(hours=float(settings["link_window_h"]))
    posts = tiktok.merged_posts(tiktok.read_history(account, config=config))
    sidecars = _read_sidecars(config)  # d'abord : un sidecar illisible est une LearningError, pas une TikTokError
    taken = {found["post_id"] for found in tiktok._published_posts(account, config)}
    stamp = _now_iso(now)
    linked: list[dict[str, str]] = []
    unlinked: list[dict[str, Any]] = []

    for path, sidecar in sidecars:
        post = sidecar.get("tiktok_post")
        if not isinstance(post, dict) or post.get("account") != account or post.get("id") or post.get("url"):
            continue
        video_id, clip_id = path.parent.name, path.stem
        planned = tiktok._naive_utc(post.get("publish_at"))
        wanted = _wanted_caption(sidecar)
        matches = []
        for post_id, seen in posts.items():
            if post_id in taken or planned is None or not _caption_matches(wanted, seen.get("caption")):
                continue
            posted = tiktok._naive_utc(seen.get("posted_at"))
            if posted is not None and abs(posted - planned) <= window:
                matches.append(post_id)
        if len(matches) == 1:
            post_id = matches[0]
            url = posts[post_id].get("post_url")
            channel = _entry_channel(video_id, clip_id, config)
            if channel is not None:
                publish.attach_post(video_id, clip_id, channel, post_url=url, post_id=post_id,
                                    state_dir=config.section("publish")["state_dir"] if config is not None else None)
            sidecar["tiktok_post"] = {**post, "id": post_id, "url": url, "linked_by": "stats", "linked_at": stamp}
            channel_mod.atomic_write_json(path, sidecar)
            taken.add(post_id)
            linked.append({"video_id": video_id, "clip_id": clip_id, "post_id": post_id})
        else:
            unlinked.append({"video_id": video_id, "clip_id": clip_id, "account": account,
                             "reason": "ambiguous" if matches else "none", "matches": sorted(matches),
                             "checked_at": stamp})

    links = _read_links(settings)
    mine = {(r["video_id"], r["clip_id"]) for r in [*unlinked, *linked]}
    kept = [r for r in links["unlinked"] if r.get("account") != account or (r["video_id"], r["clip_id"]) not in mine]
    links["unlinked"] = kept + unlinked
    counts = {"linked": links["counts"].get(account, {}).get("linked", 0) + len(linked)}
    counts.update({reason: sum(1 for r in unlinked if r["reason"] == reason) for reason in REASONS})
    links["counts"][account] = counts
    _write_links(settings, links)
    return {"linked": linked, "unlinked": {reason: counts[reason] for reason in REASONS}}


def link_if_due(now: datetime, *, config: Config | None = None) -> list[dict[str, str]]:
    """Passage du worker : traite chaque compte TikTok dont le dernier releve est plus recent que son dernier
    passage (ou jamais traite), note ``last_run`` et rend les rattachements faits. Coupe par ``enabled``."""
    settings = _settings(config)
    if not settings["enabled"]:
        return []
    stats_dir = Path(tiktok.get_settings(config)["stats_dir"])
    accounts = sorted(p.name for p in stats_dir.iterdir() if p.is_dir()) if stats_dir.is_dir() else []
    done: list[dict[str, str]] = []
    for account in accounts:
        history = tiktok.read_history(account, config=config)
        if not history:
            continue
        links = _read_links(settings)
        last = links["last_run"].get(account)
        if last is not None and datetime.fromisoformat(history[-1]["fetched_at"]) <= datetime.fromisoformat(last):
            continue
        done.extend(link_posts(account, config=config, now=now)["linked"])
        with channel_mod.file_lock(_links_path(settings)):
            links = _read_links(settings)
            links["last_run"][account] = now.isoformat()
            _write_links(settings, links)
    return done


# ---------------------------------------------------------------- versement stats -> outcomes (SPEC-00db R2-R5, R9)

_CLIP_ID = re.compile(r"(\d{2,})(?:-p\d+)?")
_SYNC_EMPTY: dict[str, Any] = {"last_sync": None, "last_error": None, "results": [], "scored": [], "excluded": [],
                               "accounts": {}, "calibration": None}


def _sync_path(settings: dict[str, Any]) -> Path:
    return Path(settings["state_dir"]) / "sync.json"


def _read_sync(settings: dict[str, Any]) -> dict[str, Any]:
    path = _sync_path(settings)
    if not path.exists():
        return {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in _SYNC_EMPTY.items()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("objet JSON attendu")
    except (OSError, ValueError) as exc:
        raise LearningError(f"état du versement illisible ({path}) : {exc}") from exc
    return {**_SYNC_EMPTY, **data}


def record_error(config: Config | None, where: str, exc: BaseException, now: datetime | None = None) -> None:
    """Écrit l'erreur dans ``sync.json.last_error`` (``{at, where, message}``) ; le prochain versement réussi l'efface."""
    settings = _settings(config)
    with channel_mod.file_lock(_sync_path(settings)):
        state = _read_sync(settings)
        state["last_error"] = {"at": _now_iso(now), "where": where, "message": str(exc)}
        channel_mod.atomic_write_json(_sync_path(settings), state)


def _moment_id(video_id: str, clip_id: str) -> int:
    found = _CLIP_ID.fullmatch(clip_id)
    if not found:
        raise LearningError(f"clip_id {clip_id!r} de {video_id} : la forme NN ou NN-pK est attendue (captions._clip_id)")
    return int(found[1])


def _aware(stamp: str) -> datetime:
    moment = datetime.fromisoformat(stamp)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class _Account:
    """Relevés d'un compte : pour chaque post, le relevé de maturité retenu, et la référence du rang."""

    def __init__(self, history: list[dict[str, Any]], settings: dict[str, Any], now: datetime) -> None:
        self.latest = tiktok.merged_posts(history)
        self.mature: dict[str, tuple[datetime, str, int, datetime]] = {}  # post -> (fetched, fetched_at, views, posted)
        maturity = timedelta(days=float(settings["maturity_days"]))
        for snapshot in history:
            fetched = _aware(snapshot["fetched_at"])
            for post in snapshot["posts"]:
                posted = tiktok._naive_utc(post.get("posted_at"))
                views = post.get("views")
                if post["post_id"] in self.mature or posted is None or views is None or fetched - posted < maturity:
                    continue
                self.mature[post["post_id"]] = (fetched, snapshot["fetched_at"], views, posted)
        since = now - timedelta(days=float(settings["window_days"]))
        self.reference = {pid: views for pid, (_, _, views, posted) in self.mature.items() if since <= posted <= now}
        self.viewed = sum(1 for views in self.reference.values() if views > 0)
        self.eligible = self.viewed >= settings["min_account_posts"]

    def percentile(self, post_id: str) -> float:
        """Rang fractionnaire 0-1 des vues à maturité du post parmi la référence (ex aequo : rang moyen)."""
        reference = {**self.reference, post_id: self.mature[post_id][2]}
        own = reference[post_id]
        less = sum(1 for v in reference.values() if v < own)
        equal = sum(1 for v in reference.values() if v == own)
        return 0.5 if len(reference) == 1 else (less + (equal + 1) / 2 - 1) / (len(reference) - 1)


def _history_accounts(config: Config | None) -> list[str]:
    stats_dir = Path(tiktok.get_settings(config)["stats_dir"])
    return sorted(p.name for p in stats_dir.iterdir() if p.is_dir()) if stats_dir.is_dir() else []


def _post_id_of(post: dict[str, Any]) -> str | None:
    if post.get("id"):
        return str(post["id"])
    found = tiktok._POST_ID.search(post["url"]) if post.get("url") else None
    return found.group(1) if found else None


def _moment(config: Config | None, video_id: str, moment_id: int, cache: dict[str, Any]) -> dict[str, Any] | None:
    if video_id not in cache:
        path = Path(config.workspace_dir if config is not None else "workspace") / video_id / "moments.json"
        cache[video_id] = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                cache[video_id] = {m["id"]: m for m in data["moments"]}
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise LearningError(f"moments.json illisible ({path}) : {exc}") from exc
    return (cache[video_id] or {}).get(moment_id)


def _journal_keys(journal_path: str) -> dict[str, set[str]]:
    keys: dict[str, set[str]] = {"result": set(), "stats": set()}
    for entry in outcomes.read(journal_path):
        if entry.get("kind") in keys and entry.get("video_id") and entry.get("clip_id"):
            keys[entry["kind"]].add(f"{entry['video_id']}/{entry['clip_id']}")
    return keys


def sync(now: datetime, *, config: Config | None = None) -> dict[str, Any]:
    """Verse les résultats dans le journal ``clipper.outcomes`` (SPEC-00db R2-R3, R9) : pour chaque clip relié
    (``tiktok_post.id`` présent dans les relevés du compte), une entrée ``result`` une seule fois et, dès que le
    clip est mûr et son compte éligible, une entrée ``stats`` une seule fois (``views_percentile`` : rang des vues
    à maturité parmi les posts mûrs du compte). Un compte youtube, un compte sous ``min_account_posts``, un clip
    trop jeune : rien dans ``stats``, la raison dans ``sync.json.excluded``. Après l'ajout d'au moins une entrée,
    recalibre les poids du jury (R5) avec les traces de ``moments.json``. Rend le contenu de ``sync.json``."""
    settings = _settings(config)
    journal_path = (config.section("outcomes") if config is not None else outcomes.CONFIG_DEFAULTS)["journal_path"]
    stamp = _now_iso(now)
    with channel_mod.file_lock(_sync_path(settings)):  # plusieurs workers : un seul verse à la fois
        state = _read_sync(settings)
        sidecars = _read_sidecars(config)
        youtube_accounts = ({a["id"] for a in accounts_mod.list_accounts(config) if a.get("service") == "youtube"}
                            if config is not None else set())
        done = _journal_keys(journal_path)
        results, scored = set(state["results"]) | done["result"], set(state["scored"]) | done["stats"]
        views = {}
        for account in _history_accounts(config):
            history = tiktok.read_history(account, config=config)
            if history:
                views[account] = _Account(history, settings, now)
        excluded: list[dict[str, Any]] = []
        linked: list[tuple[str, str, int]] = []  # clips reliés, pour la calibration
        added = 0
        moments: dict[str, Any] = {}

        for path, sidecar in sidecars:
            video_id, clip_id = path.parent.name, path.stem
            if isinstance(sidecar.get("youtube_post"), dict):
                excluded.append({"video_id": video_id, "clip_id": clip_id, "account": sidecar["youtube_post"].get("account"),
                                 "reason": "service_without_stats"})
                continue
            post = sidecar.get("tiktok_post")
            if not isinstance(post, dict) or _post_id_of(post) is None:
                continue
            account, post_id, key = post.get("account"), _post_id_of(post), f"{video_id}/{clip_id}"
            where = {"video_id": video_id, "clip_id": clip_id, "account": account}
            if account in youtube_accounts:
                excluded.append({**where, "reason": "service_without_stats"})
                continue
            moment_id = _moment_id(video_id, clip_id)
            seen = views.get(account)
            if seen is None or post_id not in seen.latest:
                excluded.append({**where, "reason": "not_in_stats"})
                continue
            linked.append((video_id, clip_id, moment_id))
            if key not in results:
                outcomes.record(video_id, clip_id, moment_id, qa=sidecar.get("qa"), human_decision=None, path=journal_path)
                results.add(key)
                added += 1
            if post_id not in seen.mature:
                excluded.append({**where, "reason": "immature"})
            elif not seen.eligible:
                excluded.append({**where, "reason": "account_below_min"})
            elif key not in scored:
                fetched, fetched_at, at_maturity, posted = seen.mature[post_id]
                row = seen.latest[post_id]
                entry = {
                    "kind": "stats", "video_id": video_id, "clip_id": clip_id, "moment_id": moment_id, "post_id": post_id,
                    "account": account, "posted_at": row.get("posted_at"), "fetched_at": fetched_at,
                    "age_days": round((fetched - posted).total_seconds() / 86400, 2),
                    "stats": {"views": row.get("views"), "views_at_maturity": at_maturity,
                              "views_percentile": seen.percentile(post_id),
                              **{k: row.get(k) for k in ("likes", "comments", "shares", "avg_watch_s", "watched_full",
                                                         "new_followers")}},
                    "recorded_at": stamp,
                }
                if (_moment(config, video_id, moment_id, moments) or {}).get("exploration") is True:
                    entry["exploration"] = True
                outcomes._append(entry, journal_path)
                scored.add(key)
                added += 1

        state.update(
            last_sync=stamp, results=sorted(results), scored=sorted(scored), excluded=excluded,
            accounts={a: {"mature_posts": len(v.reference), "viewed_posts": v.viewed, "eligible": v.eligible}
                      for a, v in sorted(views.items())})
        retry = isinstance(state["last_error"], dict) and state["last_error"].get("where") == "calibrate"
        state["last_error"] = None
        if added or retry:
            try:
                state["calibration"] = _calibrate(linked, config, now, moments)
            except Exception as exc:
                state["last_error"] = {"at": stamp, "where": "calibrate", "message": str(exc)}
                channel_mod.atomic_write_json(_sync_path(settings), state)
                exc.where = "calibrate"  # type: ignore[attr-defined]
                raise
        channel_mod.atomic_write_json(_sync_path(settings), state)
        return state


def _calibrate(linked: list[tuple[str, str, int]], config: Config | None, now: datetime, cache: dict[str, Any]) -> dict[str, Any]:
    """Recalibre les poids du jury (R5) avec les clips reliés dont le moment porte ``jury.trace`` ; les autres sont comptés."""
    traces: dict[tuple[str, int], dict[str, Any]] = {}
    untraced = 0
    for video_id, _, moment_id in linked:
        trace = ((_moment(config, video_id, moment_id, cache) or {}).get("jury") or {}).get("trace")
        if trace is None:
            untraced += 1
        else:
            traces[(video_id, moment_id)] = {"video_id": video_id, "moment_id": moment_id, "candidate": {"trace": trace}}
    jury_calibration.calibrate(list(traces.values()), config=config, now=now)
    weights = (config.section("jury_calibration") if config is not None else jury_calibration.CONFIG_DEFAULTS)["weights_path"]
    return {"at": _now_iso(now), "clips": len(traces), "untraced": untraced, "weights_path": str(weights)}


def _snapshot_newer_than_sync(settings: dict[str, Any], config: Config | None) -> bool:
    last = _read_sync(settings)["last_sync"]
    for account in _history_accounts(config):
        history = tiktok.read_history(account, config=config)
        if history and (last is None or _aware(history[-1]["fetched_at"]) > _aware(last)):
            return True
    return False


def run_if_due(now: datetime, *, config: Config | None = None) -> dict[str, Any]:
    """Passage du worker (SPEC-00db R4) : ``link_if_due``, puis ``sync`` seulement si un relevé est plus récent que
    ``sync.json.last_sync``. Coupé par ``enabled``. Une erreur porte ``where`` (``link`` | ``sync`` | ``calibrate``) et
    remonte : le worker l'écrit dans ``sync.json.last_error`` et la journalise."""
    settings = _settings(config)
    if not settings["enabled"]:
        return {"linked": [], "synced": False}
    try:
        linked = link_if_due(now, config=config)
    except Exception as exc:
        exc.where = "link"  # type: ignore[attr-defined]
        raise
    due = _snapshot_newer_than_sync(settings, config)
    if due:
        try:
            sync(now, config=config)
        except Exception as exc:
            if not hasattr(exc, "where"):
                exc.where = "sync"  # type: ignore[attr-defined]
            raise
    return {"linked": linked, "synced": due}
