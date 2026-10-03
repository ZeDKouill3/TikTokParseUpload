"""File de publication par chaine (SPEC-74e9 4, ADR-35b7 3).

Bibliotheque, pas une etape (ADR-b16b) : lit les sidecars de clip
(output/<video_id>/<clip_id>.json, SPEC-6a47) et les creneaux de la chaine
via clipper.channel.next_slots. Une entree par clip dans
state/publish/<chaine>.json (liste JSON, ecriture atomique tmp+replace ; chaque
cycle lecture-modification-ecriture est sous verrou de fichier
inter-processus, l'API web et le worker etant deux processus).

Le re-rendu du titre d'ecran et l'autopost ne sont pas ici (voir la tache
pipeline / worker).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from clipper import channel as channel_mod
from clipper import tiktok, youtube
from clipper.config import ConfigError

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

CONFIG_DEFAULTS: dict[str, object] = {
    "state_dir": "state/publish",
    "series_default_interval_h": 4,  # intervalle propose par defaut dans le formulaire « Programmer une serie »
}

TIKTOK_STATES = ("published", "scheduled_on_tiktok")
YOUTUBE_STATES = ("published", "scheduled_on_youtube")
SERVICE_STATES = {"tiktok": TIKTOK_STATES, "youtube": YOUTUBE_STATES}
SERVICE_LABELS = {"tiktok": "TikTok", "youtube": "YouTube"}
PUBLISH_MODES = ("immediate", "scheduled")
_POSTPONE_FIRST_BATCH = 8
_POSTPONE_MAX_SLOTS = 512
VALID_STATUSES = ("approved", "scheduled", "published", "failed", "rejected")
_NON_EDITABLE_STATUSES = ("scheduled", "published")
_NON_MOVABLE_STATUSES = ("rejected", "published")
_PREVIOUS_PART_STATUSES = ("approved", "scheduled")
_ENTRY_FIELDS = (
    "video_id", "clip_id", "series_id", "part", "status",
    "slot_at", "decided_at", "published_at", "error",
)


# File des clips d'une video sans chaine (SPEC-1ed3 R3) : state/publish/_sans_chaine.json ; le compte de
# chaque entree suffit, aucun preset n'est lu.
NO_CHANNEL = "_sans_chaine"
_NO_CHANNEL_LABEL = "Sans chaîne"


class PublishError(Exception):
    """Entree invalide, clip inconnu/non pret, ou creneau invalide/pris."""


class LimitError(PublishError):
    """Plafond du compte depasse (SPEC-1ed3 R4) : ``reason`` le dit, ``next_at`` est la prochaine heure possible
    (None si aucune dans les 60 jours)."""

    def __init__(self, reason: str, next_at: datetime | None, tz: ZoneInfo) -> None:
        when = next_at.astimezone(tz).strftime("%Y-%m-%d %H:%M") if next_at else "aucune dans les 60 jours"
        super().__init__(f"{reason} ; prochaine heure possible : {when}")
        self.reason, self.next_at = reason, next_at


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _state_dir(state_dir: str | Path | None) -> Path:
    return Path(state_dir) if state_dir is not None else Path(CONFIG_DEFAULTS["state_dir"])


def _state_path(channel: str, state_dir: str | Path | None) -> Path:
    return _state_dir(state_dir) / f"{channel}.json"


def _validate_entry(entry: Any, path: Path) -> None:
    if not isinstance(entry, dict):
        raise PublishError(f"entree invalide dans {path} : pas un objet ({entry!r})")
    for name in _ENTRY_FIELDS:
        if name not in entry:
            raise PublishError(f"entree invalide dans {path} : champ {name!r} manquant")
    if entry["status"] not in VALID_STATUSES:
        raise PublishError(
            f"entree invalide dans {path} : champ 'status' invalide {entry['status']!r} "
            f"(attendu : {' | '.join(VALID_STATUSES)})"
        )


def _load_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise PublishError(f"fichier de publication invalide (pas une liste) : {path}")
    for entry in data:
        _validate_entry(entry, path)
    return data


def _save_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    channel_mod.atomic_write_json(path, entries)


def _locked(path: Path):
    return channel_mod.file_lock(path)


def _refuse_in_progress(entry: dict[str, Any], what: str) -> None:
    if entry.get("in_progress_since"):
        raise PublishError(
            f"{what} refusé pour {entry['video_id']}/{entry['clip_id']} : la publication est en cours "
            "(le worker pilote TikTok), attends sa fin"
        )


def _find_entry(entries: list[dict[str, Any]], video_id: str, clip_id: str) -> dict[str, Any] | None:
    for entry in entries:
        if entry["video_id"] == video_id and entry["clip_id"] == clip_id:
            return entry
    return None


def _upsert_entry(entries: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    for i, existing in enumerate(entries):
        if existing["video_id"] == entry["video_id"] and existing["clip_id"] == entry["clip_id"]:
            entries[i] = entry
            return
    entries.append(entry)


def channel_settings(channel: str, presets_dir: str | Path, base: str | Path) -> dict[str, Any]:
    """Le [channel] valide d'une chaine ; pour ``NO_CHANNEL`` (video sans chaine) les valeurs par defaut :
    aucun creneau, aucun compte par defaut (le compte est choisi par publication)."""
    if channel == NO_CHANNEL:
        return {**channel_mod.CONFIG_DEFAULTS, "display_name": _NO_CHANNEL_LABEL, "mode": ""}
    return channel_mod.load_channel(channel, presets_dir=presets_dir, base=base)[1]


def _sidecar_path(output_dir: str | Path, video_id: str, clip_id: str) -> Path:
    return Path(output_dir) / video_id / f"{clip_id}.json"


def _read_sidecar(output_dir: str | Path, video_id: str, clip_id: str) -> dict[str, Any]:
    path = _sidecar_path(output_dir, video_id, clip_id)
    if not path.exists():
        raise PublishError(f"clip introuvable : {video_id}/{clip_id} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def read_sidecar(output_dir: str | Path, video_id: str, clip_id: str) -> dict[str, Any]:
    """Le sidecar d'un clip (SPEC-6a47) ; ``PublishError`` s'il est absent."""
    return _read_sidecar(output_dir, video_id, clip_id)


def _write_sidecar(output_dir: str | Path, video_id: str, clip_id: str, data: dict[str, Any]) -> None:
    path = _sidecar_path(output_dir, video_id, clip_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _series_info(video_id: str, clip_id: str, sidecar: dict[str, Any]) -> tuple[str | None, int | None]:
    part = sidecar.get("part")
    parts_total = sidecar.get("parts_total") or 1
    if part is None or parts_total <= 1:
        return None, None
    base = clip_id.rsplit("-p", 1)[0] if "-p" in clip_id else clip_id
    return f"{video_id}:{base}", part


def _sibling_clip_ids(output_dir: str | Path, video_id: str, series_id: str, *, exclude: str) -> list[str]:
    out_dir = Path(output_dir) / video_id
    siblings = []
    for path in sorted(out_dir.glob("*.json")):
        clip_id = path.stem
        if clip_id == exclude:
            continue
        try:
            sidecar = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PublishError(f"sidecar de clip illisible (JSON corrompu) : {path} ({exc})") from exc
        other_series_id, _ = _series_info(video_id, clip_id, sidecar)
        if other_series_id == series_id:
            siblings.append(clip_id)
    return siblings


def series_clip_ids(video_id: str, clip_id: str, output_dir: str | Path = "output") -> list[str]:
    """Tous les clip_id de la serie de ``clip_id`` (lui compris), tries par numero de partie ;
    ``[clip_id]`` si le clip n'appartient a aucune serie (TASK-e99b : cocher une partie entraine
    toute sa serie). Leve ``PublishError`` si le sidecar de ``clip_id`` est introuvable ou
    illisible (ADR-ad2e : pas de repli silencieux sur un clip absent)."""
    sidecar = _read_sidecar(output_dir, video_id, clip_id)
    series_id, part = _series_info(video_id, clip_id, sidecar)
    if series_id is None:
        return [clip_id]
    members = [(part, clip_id)]
    for sibling_id in _sibling_clip_ids(output_dir, video_id, series_id, exclude=clip_id):
        sibling_sidecar = _read_sidecar(output_dir, video_id, sibling_id)
        _, sibling_part = _series_info(video_id, sibling_id, sibling_sidecar)
        members.append((sibling_part, sibling_id))
    members.sort(key=lambda m: (m[0] if m[0] is not None else 0))
    return [cid for _, cid in members]


def _next_free_slot(schedule: dict[str, Any], entries: list[dict[str, Any]], after: datetime) -> datetime:
    taken = {entry["slot_at"] for entry in entries if entry.get("slot_at") is not None}
    n = len(taken) + 1
    while True:
        candidates = channel_mod.next_slots(schedule, after, n)
        for candidate in candidates:
            if _iso(candidate) not in taken:
                return candidate
        if len(candidates) < n:
            raise PublishError("aucun creneau disponible pour ce compte")
        n += 1


def _require_previous_part(
    entries: list[dict[str, Any]], output_dir: str | Path, video_id: str,
    clip_id: str, series_id: str, part: int,
) -> None:
    """La partie N>1 d'une serie ne s'approuve que si la partie N-1 est deja
    approved ou scheduled : l'ordre des creneaux de la serie est garanti."""
    previous = None
    for sibling_id in _sibling_clip_ids(output_dir, video_id, series_id, exclude=clip_id):
        _, sibling_part = _series_info(video_id, sibling_id, _read_sidecar(output_dir, video_id, sibling_id))
        if sibling_part == part - 1:
            previous = sibling_id
            break
    if previous is None:
        raise PublishError(f"partie {part - 1} introuvable pour approuver {video_id}/{clip_id} (partie {part})")
    entry = _find_entry(entries, video_id, previous)
    status = entry["status"] if entry is not None else "absente de la file"
    if entry is None or status not in _PREVIOUS_PART_STATUSES:
        raise PublishError(
            f"approbation refusee pour {video_id}/{clip_id} (partie {part}) : la partie {part - 1} "
            f"({previous}) doit etre approved ou scheduled, elle est {status!r}"
        )


def approve(
    video_id: str,
    clip_id: str,
    channel: str,
    *,
    now: datetime | None = None,
    output_dir: str | Path = "output",
    state_dir: str | Path | None = None,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
    account: str | None = None,
    schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Approuve un clip (SPEC-74e9 4.2) : entree 'approved', puis 'scheduled'
    au prochain creneau libre si le compte en a. Leve PublishError si le
    sidecar dit ready=false ou si ``account`` manque : le compte de publication (SPEC-6076 R2) se choisit a
    chaque publication, un style n'en porte plus. ``schedule`` : les creneaux du compte
    (``accounts.schedule_of``) ; sans creneau, l'entree reste 'approved'."""
    sidecar = _read_sidecar(output_dir, video_id, clip_id)
    if not sidecar.get("ready"):
        raise PublishError(f"clip non pret pour publication : {video_id}/{clip_id}")
    if not account:
        raise PublishError("compte de publication manquant : choisis un compte prêt à publier")

    series_id, part = _series_info(video_id, clip_id, sidecar)
    channel_settings(channel, presets_dir, base)  # style inconnu ou illisible : erreur explicite

    path = _state_path(channel, state_dir)
    now_dt = _now(now)

    entry: dict[str, Any] = {
        "video_id": video_id,
        "clip_id": clip_id,
        "series_id": series_id,
        "part": part,
        "status": "approved",
        "slot_at": None,
        "decided_at": _iso(now_dt),
        "published_at": None,
        "error": None,
        "account": account,
    }
    with _locked(path):
        entries = _load_entries(path)
        if series_id is not None and part is not None and part > 1:
            _require_previous_part(entries, output_dir, video_id, clip_id, series_id, part)
        if schedule and schedule["slots"]:
            slot = _next_free_slot(schedule, entries, now_dt)
            entry["status"] = "scheduled"
            entry["slot_at"] = _iso(slot)

        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def reject(
    video_id: str,
    clip_id: str,
    channel: str,
    *,
    now: datetime | None = None,
    output_dir: str | Path = "output",
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Rejette un clip ; si c'est une partie d'une serie, rejette aussi
    toutes les autres parties (SPEC-74e9 4.2)."""
    sidecar = _read_sidecar(output_dir, video_id, clip_id)
    series_id, part = _series_info(video_id, clip_id, sidecar)

    path = _state_path(channel, state_dir)
    now_dt = _now(now)
    with _locked(path):
        entries = _load_entries(path)
        return _reject_locked(
            entries, path, video_id, clip_id, series_id, part, now_dt, output_dir,
        )


def _reject_locked(
    entries: list[dict[str, Any]], path: Path, video_id: str, clip_id: str,
    series_id: str | None, part: int | None, now_dt: datetime, output_dir: str | Path,
) -> dict[str, Any]:
    def _reject_one(cid: str, series_id: str | None, part: int | None) -> dict[str, Any]:
        existing = _find_entry(entries, video_id, cid)
        entry = dict(existing) if existing is not None else {
            "video_id": video_id, "clip_id": cid, "series_id": series_id, "part": part,
            "status": "rejected", "slot_at": None, "decided_at": None,
            "published_at": None, "error": None,
        }
        entry["status"] = "rejected"
        entry["slot_at"] = None
        entry["decided_at"] = _iso(now_dt)
        _upsert_entry(entries, entry)
        return entry

    entry = _reject_one(clip_id, series_id, part)
    if series_id is not None:
        for sibling_id in _sibling_clip_ids(output_dir, video_id, series_id, exclude=clip_id):
            sibling_sidecar = _read_sidecar(output_dir, video_id, sibling_id)
            _, sibling_part = _series_info(video_id, sibling_id, sibling_sidecar)
            _reject_one(sibling_id, series_id, sibling_part)

    _save_entries(path, entries)
    return entry


def move(
    video_id: str,
    clip_id: str,
    channel: str,
    slot_at: datetime,
    *,
    state_dir: str | Path | None = None,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
    schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deplace un clip vers un creneau libre du compte (SPEC-74e9 4.3, SPEC-6076 R2) :
    refuse un creneau deja pris ou hors des creneaux du compte (``schedule`` : ``accounts.schedule_of``)."""
    path = _state_path(channel, state_dir)
    channel_settings(channel, presets_dir, base)  # style inconnu ou illisible : erreur explicite
    if not schedule or not schedule["slots"]:
        raise PublishError(f"déplacement impossible pour {video_id}/{clip_id} : le compte n'a aucun créneau (écran Comptes)")
    with _locked(path):
        return _move_locked(path, video_id, clip_id, slot_at, schedule)


def _move_locked(
    path: Path, video_id: str, clip_id: str, slot_at: datetime, schedule: dict[str, Any],
) -> dict[str, Any]:
    entries = _load_entries(path)
    entry = _find_entry(entries, video_id, clip_id)
    if entry is None:
        raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
    if entry["status"] in _NON_MOVABLE_STATUSES:
        raise PublishError(
            f"deplacement refuse pour {video_id}/{clip_id} : statut {entry['status']!r}"
        )
    _refuse_in_progress(entry, "déplacement")

    tz = ZoneInfo(str(schedule["timezone"]))
    local_slot = slot_at.astimezone(tz)
    day = _DAYS[local_slot.weekday()]
    time_str = local_slot.strftime("%H:%M")
    if not any(s["day"] == day and s["time"] == time_str for s in schedule["slots"]):
        raise PublishError(f"creneau hors des creneaux du compte pour {video_id}/{clip_id} : {slot_at}")

    slot_iso = _iso(slot_at)
    for other in entries:
        if other is entry:
            continue
        if other.get("slot_at") == slot_iso:
            raise PublishError(f"creneau deja pris pour {video_id}/{clip_id} : {slot_at}")

    entry = dict(entry)
    entry["slot_at"] = slot_iso
    entry["status"] = "scheduled"
    _upsert_entry(entries, entry)
    _save_entries(path, entries)
    return entry


def mark_published(
    video_id: str,
    clip_id: str,
    channel: str,
    *,
    now: datetime | None = None,
    state_dir: str | Path | None = None,
    output_dir: str | Path = "output",
    tiktok_state: str | None = None,
    post_url: str | None = None,
    post_id: str | None = None,
    publish_at: str | None = None,
    post_note: str | None = None,
    account: str | None = None,
    service: str = "tiktok",
) -> dict[str, Any]:
    """Marque un clip publie (SPEC-74e9 4.3). A la main, sans argument de plus ; apres une
    publication TikTok (SPEC-9225 R3), ``tiktok_state`` (``published`` | ``scheduled_on_tiktok``),
    l'URL ou l'id du post et ``publish_at`` (l'instant ou le post est en ligne) sont enregistres
    dans l'entree ET dans le sidecar du clip (champ ``tiktok_post``). Pour un compte YouTube (SPEC-5e50 R2),
    ``service="youtube"`` : etat ``published`` | ``scheduled_on_youtube``, URL ``youtube.com/shorts/<id>``,
    sidecar ``youtube_post`` (les champs ``tiktok_state`` / ``tiktok_publish_at`` de l'entree servent aux deux services)."""
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        if entry["status"] != "scheduled":
            raise PublishError(
                f"publication manuelle refusee pour {video_id}/{clip_id} : statut {entry['status']!r} "
                "(attendu : 'scheduled')"
            )

        entry = dict(entry)
        entry["status"] = "published"
        entry["published_at"] = _iso(_now(now))
        entry["error"], entry["capture"], entry["halted"] = None, None, False
        entry["waiting_reason"] = None
        entry["in_progress_since"] = None
        if tiktok_state is not None:
            if service not in SERVICE_STATES:
                raise PublishError(f"service invalide : {service!r} (attendu : {' | '.join(SERVICE_STATES)})")
            states = SERVICE_STATES[service]
            if tiktok_state not in states:
                raise PublishError(f"etat {SERVICE_LABELS[service]} invalide : {tiktok_state!r} "
                                   f"(attendu : {' | '.join(states)})")
            entry.update(tiktok_state=tiktok_state, post_url=post_url, post_id=post_id,
                         tiktok_publish_at=publish_at, post_note=post_note, service=service)
            sidecar = _read_sidecar(output_dir, video_id, clip_id)
            sidecar["tiktok_post" if service == "tiktok" else "youtube_post"] = {
                "url": post_url, "id": post_id, "state": tiktok_state, "publish_at": publish_at,
                "account": account, "note": post_note,
            }
            _write_sidecar(output_dir, video_id, clip_id, sidecar)
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def mark_failed(
    video_id: str,
    clip_id: str,
    channel: str,
    reason: str,
    *,
    capture: str | Path | None = None,
    halted: bool = False,
    state_dir: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Echec d'une publication (SPEC-9225 R4) : statut ``failed`` avec la raison et la capture
    d'ecran ; ``halted`` arrete le compte tant que l'entree n'est pas reessayee (``retry``)."""
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        if entry["status"] not in ("approved", "scheduled", "failed"):
            raise PublishError(f"echec impossible pour {video_id}/{clip_id} : statut {entry['status']!r}")
        entry = dict(entry)
        entry.update(status="failed", error=reason, capture=str(capture) if capture else None, halted=halted,
                     failed_at=_iso(_now(now)), waiting_reason=None, in_progress_since=None)
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def retry(
    video_id: str,
    clip_id: str,
    channel: str,
    *,
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Remet une entree ``failed`` en attente (bouton « Reessayer ») : ``scheduled`` sur son
    creneau (``approved`` sans creneau), raison, capture et arret du compte effaces."""
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        if entry["status"] != "failed":
            raise PublishError(
                f"reessai refuse pour {video_id}/{clip_id} : statut {entry['status']!r} (attendu : 'failed')"
            )
        entry = dict(entry)
        entry.update(status="scheduled" if entry["slot_at"] else "approved", error=None, capture=None, halted=False)
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def set_mode(
    video_id: str,
    clip_id: str,
    channel: str,
    mode: str | None,
    *,
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Mode de publication d'une entree (``immediate`` | ``scheduled``), ou ``None`` pour
    retomber sur ``[tiktok] publish_mode``."""
    if mode not in (None, *PUBLISH_MODES):
        raise PublishError(f"mode de publication invalide : {mode!r} (attendu : {' | '.join(PUBLISH_MODES)})")
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        entry = dict(entry)
        entry["publish_mode"] = mode
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def list_entries(channel: str, *, state_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Les entrees de state/publish/<chaine>.json (validees)."""
    return _load_entries(_state_path(channel, state_dir))


def entry_account(entry: dict[str, Any]) -> str | None:
    """Compte qui publie une entree (SPEC-00d1 R4) : celui enregistre dans l'entree, None s'il n'y en a pas
    (SPEC-6076 R2 : un style n'a plus de compte, jamais un autre compte en repli)."""
    return entry.get("account") or None


def _account_entries(
    account: str, state_dir: str | Path | None, presets_dir: str | Path, base: str | Path,
) -> list[tuple[str, dict[str, Any]]]:
    """(chaine, entree) de toutes les entrees publiees par ``account`` (SPEC-00d1 R4), toutes chaines."""
    found: list[tuple[str, dict[str, Any]]] = []
    try:
        for name in [*channel_mod.list_channels(presets_dir), NO_CHANNEL]:
            found.extend((name, e) for e in _load_entries(_state_path(name, state_dir))
                         if entry_account(e) == account)
    except (channel_mod.ChannelError, ConfigError) as exc:
        raise PublishError(f"chaines illisibles pour le compte {account} : {exc}") from exc
    return found


def account_publish_times(
    account: str, *, state_dir: str | Path | None = None, presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
) -> list[datetime]:
    """Instants des posts deja faits ou programmes du compte, toutes chaines : ``tiktok_publish_at``
    (l'instant ou le post est en ligne), sinon ``published_at`` (publication manuelle)."""
    times = []
    for _name, entry in _account_entries(account, state_dir, presets_dir, base):
        stamp = entry.get("tiktok_publish_at") or entry.get("published_at")
        if entry["status"] == "published" and stamp:
            times.append(datetime.fromisoformat(stamp))
    return sorted(times)


def halted_account(
    account: str, *, state_dir: str | Path | None = None, presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
) -> dict[str, Any] | None:
    """La premiere entree ``failed`` qui arrete le compte (R4), ou None : le worker n'y
    publie plus rien avant son « Reessayer »."""
    for name, entry in _account_entries(account, state_dir, presets_dir, base):
        if entry["status"] == "failed" and entry.get("halted"):
            return {**entry, "channel": name}
    return None


def last_failure(
    account: str, *, state_dir: str | Path | None = None, presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
) -> dict[str, Any] | None:
    """Le dernier echec de publication du compte (entree ``failed`` la plus recente) avec sa chaine, ou None."""
    failed = [(name, e) for name, e in _account_entries(account, state_dir, presets_dir, base) if e["status"] == "failed"]
    if not failed:
        return None
    name, entry = max(failed, key=lambda f: f[1].get("failed_at") or "")
    return {**entry, "channel": name}


def set_account(
    video_id: str,
    clip_id: str,
    channel: str,
    account: str,
    *,
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Compte de publication d'une entree (SPEC-00d1 R4), modifiable tant qu'elle n'est pas publiee. Que le compte
    soit pret a publier est verifie par l'appelant (la console) et, a la publication, par le worker."""
    if not isinstance(account, str) or not account:
        raise PublishError("compte de publication manquant : un identifiant de compte est attendu")
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        if entry["status"] in ("published", "rejected"):
            raise PublishError(f"changement de compte refusé pour {video_id}/{clip_id} : statut {entry['status']!r}")
        _refuse_in_progress(entry, "changement de compte")
        entry = dict(entry)
        entry["account"] = account
        entry["waiting_reason"] = None
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def set_waiting_reason(
    video_id: str,
    clip_id: str,
    channel: str,
    reason: str | None,
    *,
    state_dir: str | Path | None = None,
) -> bool:
    """Raison pour laquelle une entree ``scheduled`` reste en attente sans etre tentee (compte pas pret, connexion
    expiree ; SPEC-00d1 R4), ou None une fois levee. Rend True si la raison a change."""
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        if entry.get("waiting_reason") == reason:
            return False
        entry = dict(entry)
        entry["waiting_reason"] = reason
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return True


def postpone(
    video_id: str,
    clip_id: str,
    channel: str,
    reason: str,
    *,
    allowed: Callable[[datetime], str | None],
    schedule: dict[str, Any] | None = None,
    now: datetime | None = None,
    state_dir: str | Path | None = None,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
) -> dict[str, Any]:
    """Reporte une entree ``scheduled`` au prochain creneau libre du compte (``schedule`` :
    ``accounts.schedule_of``) que ``allowed`` accepte (``allowed(creneau)`` rend None, ou la raison du refus :
    plafonds de R6) ; la raison et la nouvelle date sont gardees dans ``postponed_reason``."""
    channel_settings(channel, presets_dir, base)  # style inconnu ou illisible : erreur explicite
    if not schedule or not schedule["slots"]:
        raise PublishError(f"aucun créneau libre et permis pour reporter {video_id}/{clip_id} ({reason}) : "
                           "le compte n'a aucun créneau (écran Comptes)")
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        if entry["status"] != "scheduled" or not entry["slot_at"]:
            raise PublishError(f"report impossible pour {video_id}/{clip_id} : statut {entry['status']!r} (attendu : 'scheduled')")
        taken = {e["slot_at"] for e in entries if e is not entry and e.get("slot_at")}
        after = max(datetime.fromisoformat(entry["slot_at"]), _now(now))
        slot = None
        n = _POSTPONE_FIRST_BATCH
        while slot is None and n <= _POSTPONE_MAX_SLOTS:
            slot = next((c for c in channel_mod.next_slots(schedule, after, n)
                         if _iso(c) not in taken and allowed(c) is None), None)
            n *= 2
        if slot is None:
            raise PublishError(f"aucun créneau libre et permis pour reporter {video_id}/{clip_id} ({reason})")
        entry = dict(entry)
        entry["postponed_reason"] = f"{reason} : reporté du {entry['slot_at']} au {_iso(slot)}"
        entry["slot_at"] = _iso(slot)
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def unschedule(
    video_id: str,
    clip_id: str,
    channel: str,
    *,
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Repasse un clip programme en 'approved', sans creneau."""
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        _refuse_in_progress(entry, "retour en attente")

        entry = dict(entry)
        entry["status"] = "approved"
        entry["slot_at"] = None
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def edit_caption(
    video_id: str,
    clip_id: str,
    channel: str,
    description: str,
    hashtags: list[str],
    *,
    now: datetime | None = None,
    output_dir: str | Path = "output",
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Reecrit la legende (champ sidecar 'caption') et les hashtags, avec
    edited_at (SPEC-74e9 4.5). Refuse sur une entree scheduled/published."""
    path = _state_path(channel, state_dir)
    entries = _load_entries(path)
    entry = _find_entry(entries, video_id, clip_id)
    if entry is not None and entry["status"] in _NON_EDITABLE_STATUSES:
        raise PublishError(
            f"edition refusee pour {video_id}/{clip_id} : statut {entry['status']!r}"
        )

    sidecar = _read_sidecar(output_dir, video_id, clip_id)
    sidecar["caption"] = description
    sidecar["hashtags"] = hashtags
    sidecar["edited_at"] = _iso(_now(now))
    _write_sidecar(output_dir, video_id, clip_id, sidecar)
    return sidecar


def list_pending(
    channel: str,
    *,
    workspace_dir: str | Path = "workspace",
    output_dir: str | Path = "output",
    state_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Clips ready=true des videos de cette chaine, absents du fichier de
    publication (SPEC-74e9 4.4)."""
    path = _state_path(channel, state_dir)
    entries = _load_entries(path)
    known = {(entry["video_id"], entry["clip_id"]) for entry in entries}

    workspace_root = Path(workspace_dir)
    pending: list[dict[str, Any]] = []
    if not workspace_root.is_dir():
        return pending

    for video_dir in sorted(workspace_root.iterdir()):
        if not video_dir.is_dir():
            continue
        pipeline_path = video_dir / "pipeline.json"
        if not pipeline_path.exists():
            continue
        state = json.loads(pipeline_path.read_text(encoding="utf-8"))
        if state.get("channel") != channel:
            continue

        video_id = video_dir.name
        out_dir = Path(output_dir) / video_id
        if not out_dir.is_dir():
            continue
        for clip_path in sorted(out_dir.glob("*.json")):
            clip = json.loads(clip_path.read_text(encoding="utf-8"))
            if clip.get("ready") and (video_id, clip_path.stem) not in known:
                pending.append(clip)

    return pending


# --------------------------------------------------------------------------
# Publication pilotee depuis l'ecran Publication (SPEC-1ed3) : le formulaire
# « Nouvelle publication » cree l'entree (approbation implicite), ni creneau de
# chaine ni etape d'approbation separee. Maintenant : due tout de suite ;
# Programmer : le worker la programme sur TikTok quand la date entre dans la
# fenetre de TikTok (SPEC-9225 R3), d'ici la Clipper la garde.
# --------------------------------------------------------------------------

_POSTABLE_STATUSES = ("approved",)  # un clip approuve a l'ancienne (sans creneau) se programme depuis le formulaire
_CANCELLABLE_STATUSES = ("approved", "scheduled", "failed")


def _tz(channel_dict: dict[str, Any]) -> ZoneInfo:
    return ZoneInfo(str(channel_dict["timezone"]))


def service_settings(service: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reglages du service (plafonds, fenetre de programmation, reglages par defaut d'un post) : ``settings`` s'il est
    donne, sinon les valeurs par defaut du module du service."""
    if service not in SERVICE_STATES:
        raise PublishError(f"service invalide : {service!r} (attendu : {' | '.join(SERVICE_STATES)})")
    if settings is not None:
        return dict(settings)
    return dict(youtube.CONFIG_DEFAULTS if service == "youtube" else tiktok.CONFIG_DEFAULTS)


def _check_post_input(
    mode: Any, account: Any, publish_at: datetime | None, options: dict[str, Any] | None,
    settings: dict[str, Any], now: datetime, service: str = "tiktok",
) -> dict[str, Any]:
    """Validation commune a la creation et a la modification ; rend les options validees."""
    if mode not in PUBLISH_MODES:
        raise PublishError(f"mode de publication invalide : {mode!r} (attendu : {' | '.join(PUBLISH_MODES)})")
    if not isinstance(account, str) or not account:
        raise PublishError("compte de publication manquant : choisis un compte prêt à publier")
    label = SERVICE_LABELS.get(service, service)
    try:
        if service == "youtube":
            merged = youtube.post_settings(settings, options)
            youtube.check_mode(mode, merged)
        else:
            merged = tiktok.post_settings(settings, options)
    except (tiktok.TikTokError, youtube.YouTubeError) as exc:
        raise PublishError(str(exc)) from exc
    if mode == "scheduled":
        if service == "tiktok" and merged["visibility"] == "private":
            raise PublishError(
                "publication privée programmée refusée : TikTok ne programme pas une vidéo privée "
                "(« Les vidéos privées ne peuvent pas être programmées ») : choisis « Maintenant » ou une autre visibilité"
            )
        if publish_at is None:
            raise PublishError("publication programmée : une date et une heure sont requises")
        if publish_at.tzinfo is None:
            raise PublishError("publication programmée : la date doit avoir un fuseau horaire")
        if publish_at <= now:
            raise PublishError(f"publication programmée : la date {publish_at.isoformat()} est déjà passée")
        minutes = int(settings["schedule_min_minutes"])
        if publish_at < now + timedelta(minutes=minutes):
            raise PublishError(
                f"publication programmée : la date est à moins de {minutes} minutes (avance minimale de {label}) : "
                "choisis « Maintenant » ou une heure plus tardive"
            )
    return dict(options or {})


def planned_times(
    account: str, *, exclude: tuple[str, str] | None = None, state_dir: str | Path | None = None,
    presets_dir: str | Path = "presets", base: str | Path = "config.toml",
) -> list[datetime]:
    """Instants des posts deja faits ou programmes du compte (``account_publish_times``) PLUS ceux de ses
    entrees en attente ou en cours (leur ``slot_at``), toutes files : un plafond se verifie contre tout ce qui
    est deja prevu, pas seulement contre ce qui est parti. ``exclude`` ecarte l'entree qu'on modifie."""
    times = list(account_publish_times(account, state_dir=state_dir, presets_dir=presets_dir, base=base))
    for _name, entry in _account_entries(account, state_dir, presets_dir, base):
        if (entry["video_id"], entry["clip_id"]) == exclude:
            continue
        if entry["status"] in ("approved", "scheduled") and entry.get("slot_at"):
            times.append(datetime.fromisoformat(entry["slot_at"]))
    return sorted(times)


def _check_caps(
    account: str, target: datetime, exclude: tuple[str, str], settings: dict[str, Any], tz: ZoneInfo,
    state_dir: str | Path | None, presets_dir: str | Path, base: str | Path,
) -> None:
    """Plafonds par compte (SPEC-1ed3 R4, SPEC-5e50 R5 : ceux du service du compte, dans ``settings``) : un depassement est refuse ici, avec la raison et la prochaine
    heure possible, jamais reporte en silence."""
    times = planned_times(account, exclude=exclude, state_dir=state_dir, presets_dir=presets_dir, base=base)
    reason = tiktok.check_limits(times, target, settings, tz)
    if reason is not None:
        raise LimitError(reason, tiktok.next_allowed(times, target, settings, tz), tz)


def create_post(
    video_id: str,
    clip_id: str,
    channel: str | None,
    *,
    account: str,
    mode: str,
    publish_at: datetime | None = None,
    options: dict[str, Any] | None = None,
    caption: str | None = None,
    hashtags: list[str] | None = None,
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
    output_dir: str | Path = "output",
    state_dir: str | Path | None = None,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
    service: str = "tiktok",
) -> dict[str, Any]:
    """Cree l'entree de publication d'un clip depuis le formulaire (SPEC-1ed3 R3) : valider = approuver. ``channel``
    est None pour une video sans chaine (file ``NO_CHANNEL``). ``mode`` ``immediate`` : due tout de suite ;
    ``scheduled`` : due a ``publish_at`` (le worker la programme sur TikTok quand la date entre dans la fenetre).
    ``options`` : reglages par post (visibilite, commentaires, reutilisation, contenu IA, verification de contenu).
    Refuse : clip pas pret, refuse ou deja publie, deja en file, prive + programme, plafond du compte depasse.
    ``service`` (``tiktok`` | ``youtube``, celui du compte) choisit les reglages, options et plafonds valides
    (``settings`` : ceux de ce service)."""
    sidecar = _read_sidecar(output_dir, video_id, clip_id)
    if not sidecar.get("ready"):
        raise PublishError(f"clip non prêt pour publication : {video_id}/{clip_id}")
    channel = channel or NO_CHANNEL
    channel_dict = channel_settings(channel, presets_dir, base)
    settings = service_settings(service, settings)
    now_dt = _now(now)
    options = _check_post_input(mode, account, publish_at, options, settings, now_dt, service)
    when = publish_at if mode == "scheduled" else now_dt
    tz = _tz(channel_dict)
    _check_caps(account, when, (video_id, clip_id), settings, tz, state_dir, presets_dir, base)

    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        existing = _find_entry(entries, video_id, clip_id)
        if existing is not None and existing["status"] not in _POSTABLE_STATUSES:
            status = existing["status"]
            if status in ("rejected", "published"):
                raise PublishError(f"publication refusée pour {video_id}/{clip_id} : le clip est {status!r}")
            raise PublishError(
                f"{video_id}/{clip_id} est déjà dans la file de publication (statut {status!r}) : "
                "modifie ou annule l'entrée existante"
            )
        if caption is not None or hashtags is not None:
            _write_caption(output_dir, video_id, clip_id, sidecar, caption, hashtags, now_dt)
        series_id, part = _series_info(video_id, clip_id, sidecar)
        entry: dict[str, Any] = {
            "video_id": video_id, "clip_id": clip_id, "series_id": series_id, "part": part,
            "status": "scheduled", "slot_at": _iso(when), "decided_at": _iso(now_dt),
            "published_at": None, "error": None, "account": account,
            "publish_mode": mode, "post_options": options, "manual": True, "service": service,
        }
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def _write_caption(
    output_dir: str | Path, video_id: str, clip_id: str, sidecar: dict[str, Any], caption: str | None,
    hashtags: list[str] | None, now: datetime,
) -> None:
    if caption is not None:
        if not isinstance(caption, str) or not caption.strip():
            raise PublishError("légende vide : une légende est obligatoire pour publier")
        sidecar["caption"] = caption
    if hashtags is not None:
        if not isinstance(hashtags, list) or not all(isinstance(h, str) for h in hashtags):
            raise PublishError("hashtags invalides : une liste de textes est attendue")
        sidecar["hashtags"] = hashtags
    sidecar["edited_at"] = _iso(now)
    _write_sidecar(output_dir, video_id, clip_id, sidecar)


_UNSET: Any = object()


def update_post(
    video_id: str,
    clip_id: str,
    channel: str | None,
    *,
    account: Any = _UNSET,
    mode: Any = _UNSET,
    publish_at: Any = _UNSET,
    options: Any = _UNSET,
    caption: str | None = None,
    hashtags: list[str] | None = None,
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
    output_dir: str | Path = "output",
    state_dir: str | Path | None = None,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
    service: str = "tiktok",
) -> dict[str, Any]:
    """Modifie une entree de publication (SPEC-1ed3 R5) tant qu'elle n'est ni en cours ni publiee. Les champs
    omis sont conserves ; l'ensemble est revalide comme a la creation (prive + programme, date, plafonds).
    ``service`` : celui du compte retenu (voir ``create_post``)."""
    channel = channel or NO_CHANNEL
    channel_dict = channel_settings(channel, presets_dir, base)
    settings = service_settings(service, settings)
    now_dt = _now(now)
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        if entry["status"] in ("published", "rejected"):
            raise PublishError(f"modification refusée pour {video_id}/{clip_id} : la publication est {entry['status']!r}")
        _refuse_in_progress(entry, "modification")
        new_mode = entry.get("publish_mode") if mode is _UNSET else mode
        new_account = entry.get("account") if account is _UNSET else account
        new_options = dict(entry.get("post_options") or {}) if options is _UNSET else options
        if publish_at is not _UNSET:
            new_at = publish_at
        else:
            new_at = datetime.fromisoformat(entry["slot_at"]) if entry.get("slot_at") else None
        new_options = _check_post_input(new_mode, new_account, new_at if new_mode == "scheduled" else None,
                                        new_options, settings, now_dt, service)
        when = new_at if new_mode == "scheduled" else now_dt
        _check_caps(new_account, when, (video_id, clip_id), settings, _tz(channel_dict), state_dir, presets_dir, base)
        if caption is not None or hashtags is not None:
            _write_caption(output_dir, video_id, clip_id, _read_sidecar(output_dir, video_id, clip_id),
                           caption, hashtags, now_dt)
        entry = dict(entry)
        entry.update(account=new_account, publish_mode=new_mode, slot_at=_iso(when), post_options=new_options,
                     waiting_reason=None, postponed_reason=None, service=service)
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def cancel_post(
    video_id: str,
    clip_id: str,
    channel: str | None,
    *,
    state_dir: str | Path | None = None,
) -> None:
    """Annule une publication (SPEC-1ed3 R5) : l'entree est retiree de la file, le clip redevient « a valider ».
    Refuse en cours, publiee ou deja programmee sur TikTok (a annuler dans TikTok Studio)."""
    path = _state_path(channel or NO_CHANNEL, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        _refuse_in_progress(entry, "annulation")
        if entry["status"] == "published":
            if entry.get("tiktok_state") == "scheduled_on_tiktok":
                where = " : elle est déjà programmée sur TikTok, annule-la dans TikTok Studio"
            elif entry.get("tiktok_state") == "scheduled_on_youtube":
                where = " : elle est déjà programmée sur YouTube, annule-la dans YouTube Studio"
            else:
                where = " : le clip est publié"
            raise PublishError(f"annulation refusée pour {video_id}/{clip_id}{where}")
        if entry["status"] not in _CANCELLABLE_STATUSES:
            raise PublishError(f"annulation refusée pour {video_id}/{clip_id} : statut {entry['status']!r}")
        _save_entries(path, [e for e in entries if e is not entry])


# Ce qui doit etre identique entre l'instantane du worker et l'entree relue pour qu'il la pilote.
_TAKEOVER_FIELDS: tuple[tuple[str, Callable[[dict[str, Any]], Any]], ...] = (
    ("compte", entry_account),
    ("date", lambda e: e.get("slot_at")),
    ("mode", lambda e: e.get("publish_mode")),
    ("réglages", lambda e: e.get("post_options")),
)


def mark_in_progress(
    video_id: str,
    clip_id: str,
    channel: str,
    *,
    now: datetime | None = None,
    state_dir: str | Path | None = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Le worker prend la main sur cette entree (« en cours ») : plus modifiable ni annulable ; efface par
    ``mark_published`` / ``mark_failed``. Prise atomique sous le verrou : l'entree doit etre ``scheduled``,
    pas deja en cours, et (``expected`` : l'instantane lu par le worker) avoir le meme compte, la meme date et
    les memes reglages ; sinon ``PublishError`` et rien n'est ecrit. Rend l'entree relue sous le verrou."""
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        entry = _find_entry(entries, video_id, clip_id)
        if entry is None:
            raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
        if entry["status"] != "scheduled":
            raise PublishError(f"prise en main refusée pour {video_id}/{clip_id} : statut {entry['status']!r} "
                               "(attendu : 'scheduled')")
        if entry.get("in_progress_since"):
            raise PublishError(f"prise en main refusée pour {video_id}/{clip_id} : déjà en cours depuis "
                               f"{entry['in_progress_since']}")
        if expected is not None:
            changed = [label for label, read in _TAKEOVER_FIELDS if read(entry) != read(expected)]
            if changed:
                raise PublishError(f"prise en main refusée pour {video_id}/{clip_id} : publication modifiée "
                                   f"depuis sa lecture ({', '.join(changed)}), relue au prochain passage")
        entry = dict(entry)
        entry["in_progress_since"] = _iso(_now(now))
        _upsert_entry(entries, entry)
        _save_entries(path, entries)
    return entry


def fail_interrupted(channel: str, *, now: datetime | None = None, state_dir: str | Path | None = None) -> int:
    """Une entree restee « en cours » alors que le worker demarre (arret pendant la publication) passe en echec
    explicite, reessayable : jamais bloquee en « en cours ». Rend le nombre d'entrees touchees."""
    path = _state_path(channel, state_dir)
    with _locked(path):
        entries = _load_entries(path)
        stale = [e for e in entries if e.get("in_progress_since")]
        for entry in stale:
            updated = dict(entry)
            updated.update(
                status="failed", in_progress_since=None, halted=False, capture=None, waiting_reason=None,
                failed_at=_iso(_now(now)),
                error="publication interrompue (le worker s'est arrêté pendant la publication) : "
                      "vérifie sur TikTok Studio que le post n'existe pas avant de réessayer")
            _upsert_entry(entries, updated)
        if stale:
            _save_entries(path, entries)
    return len(stale)


def all_entries(
    *, state_dir: str | Path | None = None, presets_dir: str | Path = "presets",
) -> list[tuple[str, dict[str, Any]]]:
    """(file, entree) de toutes les entrees de toutes les chaines et de la file des videos sans chaine."""
    found: list[tuple[str, dict[str, Any]]] = []
    try:
        for name in [*channel_mod.list_channels(presets_dir), NO_CHANNEL]:
            found.extend((name, e) for e in _load_entries(_state_path(name, state_dir)))
    except channel_mod.ChannelError as exc:
        raise PublishError(f"chaînes illisibles : {exc}") from exc
    return found


# --------------------------------------------------------------------------
# Série programmée (TASK-5bbf, SPEC-1ed3, SPEC-6076 R3/R6) : choix automatique
# (N meilleurs clips par score) ou manuel (ordre de selection choisi par
# l'utilisateur) de clips a publier a cadence reguliere (debut + k x X h, en
# duree reelle). Une serie en plusieurs parties est prise entiere, dans
# l'ordre, ou pas du tout ; N compte des posts (une partie = un post).
# Aucun repli silencieux (ADR-ad2e) : l'apercu (preview_series) dit chaque
# refus, la creation (create_series) est tout ou rien.
# --------------------------------------------------------------------------


def plan_series_dates(start_at: datetime, interval_hours: int, count: int) -> list[datetime]:
    """Dates d'une serie (debut + k x intervalle, k=0..count-1), en duree reelle : conversion
    en UTC puis arithmetique sur des ``timedelta`` (jamais d'arithmetique murale) : un changement
    d'heure d'ete/hiver ne decale jamais l'ecart entre deux publications."""
    if start_at.tzinfo is None:
        raise PublishError("série : la date de début doit avoir un fuseau horaire")
    if not isinstance(interval_hours, int) or isinstance(interval_hours, bool) or interval_hours < 1:
        raise PublishError("intervalle invalide : un nombre entier d'heures >= 1 est attendu (pas de demi-heure)")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise PublishError("nombre de publications invalide : un entier >= 1 est attendu")
    start_utc = start_at.astimezone(timezone.utc)
    step = timedelta(hours=interval_hours)
    return [start_utc + i * step for i in range(count)]


def _unit_members(output_dir: str | Path, video_id: str, clip_id: str, sidecar: dict[str, Any]) -> list[str]:
    """Les clip_id d'une serie (celle de ``clip_id`` incluse), tries par numero de partie ; ``[clip_id]``
    si ce n'est pas une serie en plusieurs parties."""
    series_id, part = _series_info(video_id, clip_id, sidecar)
    if series_id is None:
        return [clip_id]
    ordered = [(part or 1, clip_id)]
    for sibling_id in _sibling_clip_ids(output_dir, video_id, series_id, exclude=clip_id):
        sibling_sidecar = _read_sidecar(output_dir, video_id, sibling_id)
        _, sibling_part = _series_info(video_id, sibling_id, sibling_sidecar)
        ordered.append((sibling_part or 1, sibling_id))
    ordered.sort(key=lambda pair: pair[0])
    return [cid for _, cid in ordered]


def _eligible_units(
    output_dir: str | Path, video_id: str, channel: str | None, entries: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Unites (une serie entiere) de ce ``video_id`` pretes a publier (``ready``) et absentes de
    ``entries`` (jamais publiees, en file ni programmees) ; une partie indisponible exclut toute la serie."""
    out_dir = Path(output_dir) / video_id
    seen: set[str] = set()
    units: list[dict[str, Any]] = []
    for path in sorted(out_dir.glob("*.json")):
        clip_id = path.stem
        if clip_id in seen:
            continue
        sidecar = _read_sidecar(output_dir, video_id, clip_id)
        members = _unit_members(output_dir, video_id, clip_id, sidecar)
        seen.update(members)
        member_sidecars = [sidecar if m == clip_id else _read_sidecar(output_dir, video_id, m) for m in members]
        if not all(s.get("ready") is True for s in member_sidecars):
            continue
        if any((video_id, m) in entries for m in members):
            continue
        units.append({"video_id": video_id, "channel": channel, "clip_ids": members, "score": sidecar.get("score")})
    return units


def available_series_clips(
    style: str | None, *, workspace_dir: str | Path = "workspace", output_dir: str | Path = "output",
    state_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Unites de clips (chacune une serie entiere, parties triees) pretes a publier et absentes de toute
    file de publication, optionnellement filtrees par ``style`` (``None`` = tous les styles, y compris les
    videos sans style). L'ordre rendu n'est PAS trie par score (voir ``preview_series``)."""
    workspace_root = Path(workspace_dir)
    if not workspace_root.is_dir():
        return []
    units: list[dict[str, Any]] = []
    entries_cache: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for video_dir in sorted(p for p in workspace_root.iterdir() if p.is_dir()):
        pipeline_path = video_dir / "pipeline.json"
        if not pipeline_path.exists():
            continue
        state = json.loads(pipeline_path.read_text(encoding="utf-8"))
        channel = state.get("channel")
        if style is not None and channel != style:
            continue
        file_channel = channel or NO_CHANNEL
        if file_channel not in entries_cache:
            entries_cache[file_channel] = {
                (e["video_id"], e["clip_id"]): e for e in _load_entries(_state_path(file_channel, state_dir))
            }
        out_dir = Path(output_dir) / video_dir.name
        if not out_dir.is_dir():
            continue
        units.extend(_eligible_units(output_dir, video_dir.name, channel, entries_cache[file_channel]))
    return units


def _series_item_refusal(when: datetime, settings: dict[str, Any], now_dt: datetime, service: str) -> str | None:
    """Refus explicite (ADR-ad2e) d'une date de serie, ou None : date deja passee, sous l'avance minimale, ou
    au-dela de la fenetre de programmation du service (contrairement a ``create_post`` seul, une serie refuse
    une date hors fenetre plutot que de la garder en attente : trop de publications a surveiller a la main)."""
    label = SERVICE_LABELS.get(service, service)
    if when <= now_dt:
        return f"date déjà passée : {when.isoformat()}"
    minutes = int(settings["schedule_min_minutes"])
    if when < now_dt + timedelta(minutes=minutes):
        return (f"date à moins de {minutes} minutes (avance minimale de {label}) : "
                "choisis un début plus tardif ou un intervalle plus grand")
    days = int(settings["schedule_max_days"])
    if when > now_dt + timedelta(days=days):
        return (f"date hors fenêtre de programmation de {label} (plus de {days} jours à l'avance) : "
                "réduis le nombre de vidéos, l'intervalle, ou avance le début")
    return None


def _auto_series_units(pool: list[dict[str, Any]], count: int) -> tuple[list[dict[str, Any]], int]:
    """Les meilleures unites (score decroissant) qui tiennent dans ``count`` posts : une unite trop grande
    pour les places restantes est sautee (jamais coupee), la suivante (par score) est tentee (complement
    utilisateur du 2026-10-03)."""
    ordered = sorted(
        pool, key=lambda u: (-(u["score"] if u["score"] is not None else float("-inf")), u["video_id"], u["clip_ids"][0])
    )
    selected: list[dict[str, Any]] = []
    used = 0
    for unit in ordered:
        if used >= count:
            break
        size = len(unit["clip_ids"])
        if used + size > count:
            continue
        selected.append(unit)
        used += size
    return selected, used


def _manual_series_units(
    pool: list[dict[str, Any]], selection: list[tuple[str, str]],
) -> tuple[list[dict[str, Any]], int]:
    """Les unites choisies a la main, dans l'ordre de selection : cocher n'importe quelle partie d'une serie
    selectionne la serie entiere ; une serie deja selectionnee (par une autre de ses parties) n'est pas
    comptee deux fois. Leve ``PublishError`` si une selection ne correspond a aucune unite disponible."""
    if not selection:
        raise PublishError("série manuelle : choisis au moins un clip")
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for unit in pool:
        for clip_id in unit["clip_ids"]:
            by_key[(unit["video_id"], clip_id)] = unit

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    used = 0
    for video_id, clip_id in selection:
        unit = by_key.get((video_id, clip_id))
        if unit is None:
            raise PublishError(
                f"clip indisponible pour la série : {video_id}/{clip_id} (déjà en file, publié ou pas prêt)"
            )
        unit_key = (unit["video_id"], tuple(unit["clip_ids"]))
        if unit_key in seen:
            continue
        seen.add(unit_key)
        selected.append(unit)
        used += len(unit["clip_ids"])
    return selected, used


def preview_series(
    *,
    mode: str,
    style: str | None,
    account: str,
    service: str = "tiktok",
    interval_hours: int,
    start_at: datetime,
    count: int | None = None,
    selection: list[tuple[str, str]] | None = None,
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
    workspace_dir: str | Path = "workspace",
    output_dir: str | Path = "output",
    state_dir: str | Path | None = None,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
) -> dict[str, Any]:
    """Apercu d'une serie programmee (SPEC-1ed3, SPEC-6076 R3/R6), sans rien creer. ``mode`` ``auto`` :
    les meilleurs clips par score jusqu'a ``count`` posts (une partie = un post, une serie incomplete est
    sautee entiere). ``mode`` ``manual`` : ``selection`` (video_id, clip_id) dans l'ordre choisi par
    l'utilisateur ; cocher une partie ajoute toute sa serie. Chaque publication prevue est a
    ``start_at + k x interval_hours`` (duree reelle) ; un refus (date hors fenetre, sous l'avance minimale,
    plafond du compte) est explicite par publication (ADR-ad2e), jamais un decalage silencieux. Rend
    ``{"items", "available", "requested", "insufficient", "insufficient_reason", "ok"}`` ; ``ok`` est faux
    des qu'un item est refuse ou que la serie est incomplete."""
    if mode not in ("auto", "manual"):
        raise PublishError(f"mode de série invalide : {mode!r} (attendu : auto | manual)")
    if not account:
        raise PublishError("compte de publication manquant : choisis un compte prêt à publier")

    settings = service_settings(service, settings)
    now_dt = _now(now)
    pool = available_series_clips(style, workspace_dir=workspace_dir, output_dir=output_dir, state_dir=state_dir)

    if mode == "auto":
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise PublishError("nombre de vidéos invalide : un entier >= 1 est attendu")
        selected_units, used = _auto_series_units(pool, count)
        requested = count
    else:
        selected_units, used = _manual_series_units(pool, selection or [])
        requested = used

    dates = plan_series_dates(start_at, interval_hours, used) if used else []

    items: list[dict[str, Any]] = []
    committed: list[datetime] = list(
        planned_times(account, state_dir=state_dir, presets_dir=presets_dir, base=base)
    )
    i = 0
    for unit in selected_units:
        channel = unit["channel"] or NO_CHANNEL
        tz = _tz(channel_settings(channel, presets_dir, base))
        for clip_id in unit["clip_ids"]:
            when = dates[i]
            i += 1
            refusal = _series_item_refusal(when, settings, now_dt, service)
            if refusal is None:
                reason = tiktok.check_limits(committed, when, settings, tz)
                if reason is not None:
                    next_at = tiktok.next_allowed(committed, when, settings, tz)
                    refusal = str(LimitError(reason, next_at, tz))
                else:
                    committed.append(when)
            items.append({
                "video_id": unit["video_id"], "clip_id": clip_id, "channel": unit["channel"],
                "score": unit["score"], "publish_at": _iso(when), "refusal": refusal,
            })

    insufficient = mode == "auto" and used < count
    insufficient_reason = None
    if insufficient:
        plural = "s" if used > 1 else ""
        insufficient_reason = f"seulement {used} vidéo{plural} disponible{plural} (demandé : {count})"
    ok = not insufficient and bool(items) and all(it["refusal"] is None for it in items)
    return {
        "mode": mode, "requested": requested, "available": used,
        "insufficient": insufficient, "insufficient_reason": insufficient_reason,
        "items": items, "ok": ok,
    }


def create_series(
    *,
    mode: str,
    style: str | None,
    account: str,
    service: str = "tiktok",
    interval_hours: int,
    start_at: datetime,
    count: int | None = None,
    selection: list[tuple[str, str]] | None = None,
    settings: dict[str, Any] | None = None,
    now: datetime | None = None,
    workspace_dir: str | Path = "workspace",
    output_dir: str | Path = "output",
    state_dir: str | Path | None = None,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
) -> list[dict[str, Any]]:
    """Cree une serie programmee (SPEC-1ed3, SPEC-6076 R3/R6) : ``preview_series`` d'abord, puis une entree
    ``create_post`` par publication, dans l'ordre. Tout ou rien (ADR-ad2e) : un seul item refuse, ou moins de
    clips que demande, et RIEN n'est cree ; si la creation echoue en cours de route (etat change entre
    l'apercu et la creation), les entrees deja creees sont annulees avant de relever l'erreur."""
    preview = preview_series(
        mode=mode, style=style, account=account, service=service, interval_hours=interval_hours,
        start_at=start_at, count=count, selection=selection, settings=settings, now=now,
        workspace_dir=workspace_dir, output_dir=output_dir, state_dir=state_dir, presets_dir=presets_dir, base=base,
    )
    if preview["insufficient"]:
        raise PublishError(f"série refusée : {preview['insufficient_reason']}")
    if not preview["items"]:
        raise PublishError("série refusée : aucun clip disponible")
    bad = [it for it in preview["items"] if it["refusal"]]
    if bad:
        reasons = "; ".join(f"{it['video_id']}/{it['clip_id']} : {it['refusal']}" for it in bad)
        raise PublishError(f"série refusée (aucune publication créée) : {reasons}")

    created: list[tuple[str | None, dict[str, Any]]] = []
    try:
        for item in preview["items"]:
            when = datetime.fromisoformat(item["publish_at"])
            entry = create_post(
                item["video_id"], item["clip_id"], item["channel"], account=account, mode="scheduled",
                publish_at=when, settings=settings, now=now, output_dir=output_dir, state_dir=state_dir,
                presets_dir=presets_dir, base=base, service=service,
            )
            created.append((item["channel"], entry))
    except (PublishError, channel_mod.ChannelError, ConfigError):
        for channel, entry in created:
            try:
                cancel_post(entry["video_id"], entry["clip_id"], channel, state_dir=state_dir)
            except PublishError:
                pass
        raise
    return [entry for _, entry in created]
