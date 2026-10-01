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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from clipper import channel as channel_mod
from clipper.config import ConfigError

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

CONFIG_DEFAULTS: dict[str, object] = {
    "state_dir": "state/publish",
}

TIKTOK_STATES = ("published", "scheduled_on_tiktok")
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


class PublishError(Exception):
    """Entree invalide, clip inconnu/non pret, ou creneau invalide/pris."""


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


def _next_free_slot(channel: dict[str, Any], entries: list[dict[str, Any]], after: datetime) -> datetime:
    taken = {entry["slot_at"] for entry in entries if entry.get("slot_at") is not None}
    n = len(taken) + 1
    while True:
        candidates = channel_mod.next_slots(channel, after, n)
        for candidate in candidates:
            if _iso(candidate) not in taken:
                return candidate
        if len(candidates) < n:
            raise PublishError("aucun creneau disponible pour cette chaine")
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
) -> dict[str, Any]:
    """Approuve un clip (SPEC-74e9 4.2) : entree 'approved', puis 'scheduled'
    au prochain creneau libre si la chaine en a. Leve PublishError si le
    sidecar dit ready=false. Le compte de publication (SPEC-00d1 R4) est ``account`` s'il est donne,
    sinon celui de la chaine ([channel] tiktok_account, None s'il n'y en a pas)."""
    sidecar = _read_sidecar(output_dir, video_id, clip_id)
    if not sidecar.get("ready"):
        raise PublishError(f"clip non pret pour publication : {video_id}/{clip_id}")

    series_id, part = _series_info(video_id, clip_id, sidecar)
    _, channel_dict = channel_mod.load_channel(channel, presets_dir=presets_dir, base=base)

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
        "account": account or channel_dict["tiktok_account"] or None,
    }
    with _locked(path):
        entries = _load_entries(path)
        if series_id is not None and part is not None and part > 1:
            _require_previous_part(entries, output_dir, video_id, clip_id, series_id, part)
        if channel_dict["slots"]:
            slot = _next_free_slot(channel_dict, entries, now_dt)
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
) -> dict[str, Any]:
    """Deplace un clip vers un creneau libre de la chaine (SPEC-74e9 4.3) :
    refuse un creneau deja pris ou hors des slots de la chaine."""
    path = _state_path(channel, state_dir)
    _, channel_dict = channel_mod.load_channel(channel, presets_dir=presets_dir, base=base)
    with _locked(path):
        return _move_locked(path, video_id, clip_id, slot_at, channel_dict)


def _move_locked(
    path: Path, video_id: str, clip_id: str, slot_at: datetime, channel_dict: dict[str, Any],
) -> dict[str, Any]:
    entries = _load_entries(path)
    entry = _find_entry(entries, video_id, clip_id)
    if entry is None:
        raise PublishError(f"clip absent de la file de publication : {video_id}/{clip_id}")
    if entry["status"] in _NON_MOVABLE_STATUSES:
        raise PublishError(
            f"deplacement refuse pour {video_id}/{clip_id} : statut {entry['status']!r}"
        )

    tz = ZoneInfo(str(channel_dict["timezone"]))
    local_slot = slot_at.astimezone(tz)
    day = _DAYS[local_slot.weekday()]
    time_str = local_slot.strftime("%H:%M")
    if not any(s["day"] == day and s["time"] == time_str for s in channel_dict["slots"]):
        raise PublishError(f"creneau hors des slots de la chaine pour {video_id}/{clip_id} : {slot_at}")

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
) -> dict[str, Any]:
    """Marque un clip publie (SPEC-74e9 4.3). A la main, sans argument de plus ; apres une
    publication TikTok (SPEC-9225 R3), ``tiktok_state`` (``published`` | ``scheduled_on_tiktok``),
    l'URL ou l'id du post et ``publish_at`` (l'instant ou le post est en ligne) sont enregistres
    dans l'entree ET dans le sidecar du clip (champ ``tiktok_post``)."""
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
        if tiktok_state is not None:
            if tiktok_state not in TIKTOK_STATES:
                raise PublishError(f"etat TikTok invalide : {tiktok_state!r} (attendu : {' | '.join(TIKTOK_STATES)})")
            entry.update(tiktok_state=tiktok_state, post_url=post_url, post_id=post_id,
                         tiktok_publish_at=publish_at, post_note=post_note)
            sidecar = _read_sidecar(output_dir, video_id, clip_id)
            sidecar["tiktok_post"] = {
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
                     failed_at=_iso(_now(now)), waiting_reason=None)
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


def entry_account(entry: dict[str, Any], channel_account: str | None) -> str | None:
    """Compte qui publie une entree (SPEC-00d1 R4) : celui enregistre dans l'entree ; une entree sans ce champ
    (file d'avant R4) prend le compte de sa chaine. Jamais un autre compte en repli."""
    return entry["account"] if "account" in entry else (channel_account or None)


def _account_entries(
    account: str, state_dir: str | Path | None, presets_dir: str | Path, base: str | Path,
) -> list[tuple[str, dict[str, Any]]]:
    """(chaine, entree) de toutes les entrees publiees par ``account`` (SPEC-00d1 R4), toutes chaines."""
    found: list[tuple[str, dict[str, Any]]] = []
    try:
        names = channel_mod.list_channels(presets_dir)
        for name in names:
            _config, settings = channel_mod.load_channel(name, presets_dir=presets_dir, base=base)
            found.extend((name, e) for e in _load_entries(_state_path(name, state_dir))
                         if entry_account(e, settings["tiktok_account"]) == account)
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
    now: datetime | None = None,
    state_dir: str | Path | None = None,
    presets_dir: str | Path = "presets",
    base: str | Path = "config.toml",
) -> dict[str, Any]:
    """Reporte une entree ``scheduled`` au prochain creneau libre que ``allowed`` accepte
    (``allowed(creneau)`` rend None, ou la raison du refus : plafonds de R6) ; la raison et la
    nouvelle date sont gardees dans ``postponed_reason``."""
    _, channel_dict = channel_mod.load_channel(channel, presets_dir=presets_dir, base=base)
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
            slot = next((c for c in channel_mod.next_slots(channel_dict, after, n)
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
