"""learning.py : boucle d'apprentissage, 1/4 : rattacher apres releve les posts TikTok aux clips Clipper
sans id de post (ADR-c260, SPEC-00db R1).

Bibliotheque (ADR-b16b) : n'importe ni ``clipper.web`` ni une etape ; appelee par le worker. Un post programme
n'a pas d'adresse a la publication : le releve des Publications (SPEC-47e2) le voit ensuite avec son id et sa
legende. Rien n'est devine (ADR-ad2e) : zero ou plusieurs candidats = non relie, raison ecrite dans
``state/learning/links.json``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from clipper import channel as channel_mod
from clipper import publish, tiktok
from clipper.config import Config

CONFIG_DEFAULTS: dict[str, object] = {
    "state_dir": "state/learning",  # links.json : derniers passages et clips non relies, avec la raison
    "enabled": True,  # false : le worker ne rattache rien
    "link_window_h": 12,  # ecart maximal (heures) entre la date prevue du clip et la date du post releve
}

REASONS = ("none", "ambiguous")


class LearningError(Exception):
    """Etat ou sidecar illisible : jamais ignore, nomme le fichier."""


def _settings(config: Config | None) -> dict[str, Any]:
    settings = dict(config.section("learning")) if config is not None else dict(CONFIG_DEFAULTS)
    window = settings["link_window_h"]
    if isinstance(window, bool) or not isinstance(window, (int, float)) or window <= 0:
        raise LearningError(f"[learning] link_window_h invalide : {window!r} (un nombre d'heures > 0 est attendu)")
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
        links = _read_links(settings)
        links["last_run"][account] = now.isoformat()
        _write_links(settings, links)
    return done
