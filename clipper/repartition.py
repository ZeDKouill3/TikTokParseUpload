"""repartition.py : plan du lendemain par compte TikTok, prepare chaque soir (SPEC-78dc R0-R7).

Bibliotheque (ADR-b16b) : n'importe ni ``clipper.web`` ni une etape du pipeline ; importe ``publish``, ``accounts``,
``tiktok`` et ``channel``. Le plan est un fichier JSON atomique ``<state_dir>/<AAAA-MM-JJ>.json`` ecrit sous verrou
(ADR-35b7) : le worker le calcule (``run_if_due``), l'API le relit, le modifie et le valide. Rien n'est cree ni envoye
ici : un plan ``proposed`` n'est qu'une proposition. Aucun chiffre invente, aucun repli silencieux (ADR-ad2e) : un
reglage hors domaine, un fichier illisible ou un creneau manquant sont une ``RepartitionError`` ou une note du plan.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from clipper import accounts, channel, publish, tiktok
from clipper.config import Config, ConfigError, load_config

log = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    "enabled": True,  # faux : le worker ne calcule rien, l'ecran le dit
    "state_dir": "state/repartition",  # un fichier <AAAA-MM-JJ>.json par jour planifie
    "compute_time": "20:00",  # heure de Paris a partir de laquelle le worker calcule le plan du lendemain
    "posts_per_day": 6,  # posts vises par compte et par jour, publications deja prevues comprises
    "default_grid_start": "08:00",  # grille par defaut d'un compte sans creneau fixe ce jour-la
    "default_grid_end": "22:00",  # derniere heure de la grille par defaut (incluse)
    "default_grid_gap_min": 150,  # ecart minimal (minutes) entre deux posts d'un meme compte, grille et complements
    "account_stagger_min": 30,  # decalage (minutes) entre comptes a meme heure de grille, par rang du compte
    "max_per_source": 2,  # clips d'une meme source (jeu connu, sinon VOD) par compte et par jour
    "excluded_sources": [],  # streamers (meta.json channel) ou styles jamais planifies
    "prime_start": "18:00",  # debut des creneaux du soir (les meilleurs clips)
    "prime_end": "22:00",  # fin (incluse) des creneaux du soir
    "exploration_per_day": 1,  # clips d'exploration au plus par jour, tous comptes confondus
    "bonus_window_days": 7,  # fenetre des posts releves qui servent au bonus d'une source
    "bonus_min_posts": 2,  # posts releves d'une source au moins pour qu'elle ait un bonus
    "bonus_points": 5.0,  # amplitude maximale du bonus, en points de score
}

PARIS = ZoneInfo("Europe/Paris")
STATUSES = ("proposed", "validated", "error")
_ERROR_RETRY = timedelta(minutes=5)  # un plan en erreur n'est retente qu'apres ce delai (le tour du worker est court)
_HANDLED = (publish.PublishError, accounts.AccountsError, tiktok.TikTokError, ConfigError, OSError, ValueError)
_logged_errors: set[tuple[str, str, str]] = set()
_HM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_CLIP_NUMBER = re.compile(r"^(\d+)")


class RepartitionError(Exception):
    """Reglage hors domaine, fichier d'etat ou de travail illisible, plan deja valide : jamais corrige en silence."""


# ---------------------------------------------------------------- reglages (R0)


def _minutes(settings: dict[str, Any], key: str) -> int:
    value = settings[key]
    found = _HM.match(value) if isinstance(value, str) else None
    if not found:
        raise RepartitionError(f"[repartition] {key} invalide : {value!r} (une heure HH:MM est attendue)")
    return int(found[1]) * 60 + int(found[2])


def _integer(settings: dict[str, Any], key: str, minimum: int) -> int:
    value = settings[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RepartitionError(f"[repartition] {key} invalide : {value!r} (un entier >= {minimum} est attendu)")
    return value


def _settings(config: Config | None) -> dict[str, Any]:
    settings = dict(config.section("repartition")) if config is not None else dict(CONFIG_DEFAULTS)
    if not isinstance(settings["enabled"], bool):
        raise RepartitionError(f"[repartition] enabled invalide : {settings['enabled']!r} (true ou false est attendu)")
    if not isinstance(settings["state_dir"], str) or not settings["state_dir"]:
        raise RepartitionError(f"[repartition] state_dir invalide : {settings['state_dir']!r} (un chemin est attendu)")
    for key in ("compute_time", "default_grid_start", "default_grid_end", "prime_start", "prime_end"):
        _minutes(settings, key)
    for key, minimum in (("posts_per_day", 1), ("default_grid_gap_min", 1), ("max_per_source", 1),
                         ("bonus_window_days", 1), ("bonus_min_posts", 1), ("account_stagger_min", 0),
                         ("exploration_per_day", 0)):
        _integer(settings, key, minimum)
    if _minutes(settings, "prime_end") <= _minutes(settings, "prime_start"):
        raise RepartitionError(
            f"[repartition] prime_end ({settings['prime_end']}) doit etre apres prime_start ({settings['prime_start']})")
    if _minutes(settings, "default_grid_end") < _minutes(settings, "default_grid_start"):
        raise RepartitionError(f"[repartition] default_grid_end ({settings['default_grid_end']}) est avant "
                               f"default_grid_start ({settings['default_grid_start']})")
    points = settings["bonus_points"]
    if isinstance(points, bool) or not isinstance(points, (int, float)) or points < 0:
        raise RepartitionError(f"[repartition] bonus_points invalide : {points!r} (un nombre >= 0 est attendu)")
    sources = settings["excluded_sources"]
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise RepartitionError(f"[repartition] excluded_sources invalide : {sources!r} (une liste de chaines est attendue)")
    return settings


# ---------------------------------------------------------------- fichiers et dates


def _as_day(day: date | str) -> date:
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    try:
        return date.fromisoformat(day)
    except (TypeError, ValueError):
        raise RepartitionError(f"jour invalide : {day!r} (AAAA-MM-JJ est attendu)") from None


def _paris(moment: datetime) -> datetime:
    """Instant en heure de Paris ; une date sans fuseau est deja une heure de Paris (celle de TikTok Studio)."""
    return moment.replace(tzinfo=PARIS) if moment.tzinfo is None else moment.astimezone(PARIS)


def plan_path(day: date | str, config: Config | None = None) -> Path:
    settings = _settings(config)
    return Path(settings["state_dir"]) / f"{_as_day(day).isoformat()}.json"


def read_plan(day: date | str, config: Config | None = None) -> dict[str, Any] | None:
    """Le plan du jour, ``None`` s'il n'existe pas ; un fichier illisible est une ``RepartitionError``."""
    return _read_json(plan_path(day, config), None)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RepartitionError(f"fichier illisible : {path} ({exc})") from exc


def normalize(name: str) -> str:
    """Cle de jeu : minuscules, sans accents ni ponctuation, espaces reduits (meme regle que la veille)."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _fmt(number: float) -> str:
    return f"{int(round(number)):,}".replace(",", " ")


# ---------------------------------------------------------------- creneaux (R1)


def _is_prime(slot: datetime, settings: dict[str, Any]) -> bool:
    local = _paris(slot)
    minute = local.hour * 60 + local.minute
    return _minutes(settings, "prime_start") <= minute <= _minutes(settings, "prime_end")


def _entry_time(entry: dict[str, Any]) -> datetime | None:
    """Instant d'une entree de publication, comme ``publish.planned_times`` : publiee -> sa mise en ligne,
    approuvee ou programmee -> son creneau."""
    if entry["status"] == "published":
        stamp = entry.get("tiktok_publish_at") or entry.get("published_at")
    elif entry["status"] in ("approved", "scheduled"):
        stamp = entry.get("slot_at")
    else:
        return None
    return datetime.fromisoformat(stamp) if stamp else None


def _account_slots(
    account: dict[str, Any], rank: int, day: date, settings: dict[str, Any], planned: list[datetime],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Creneaux du jour d'un compte et notes : creneaux fixes (tous gardes), puis heures de la grille par defaut
    pour atteindre ``posts_per_day`` en comptant les publications deja prevues ce jour-la."""
    schedule = accounts.schedule_of(account)
    zone = ZoneInfo(str(schedule["timezone"]))
    fixed: list[datetime] = []
    if schedule["slots"]:
        before = datetime.combine(day, time(0, 0), zone) - timedelta(seconds=1)
        fixed = [s for s in channel.next_slots(schedule, before, len(schedule["slots"])) if s.date() == day]
    taken = list(planned)
    kept_fixed = [s for s in fixed if s not in planned]
    taken.extend(kept_fixed)
    gap = timedelta(minutes=int(settings["default_grid_gap_min"]))
    wanted = int(settings["posts_per_day"]) - len(planned) - len(kept_fixed)
    grid: list[datetime] = []
    if wanted > 0:
        start = _minutes(settings, "default_grid_start") + int(settings["account_stagger_min"]) * rank
        end = _minutes(settings, "default_grid_end")
        minute = start
        while minute <= end and len(grid) < wanted:
            candidate = datetime.combine(day, time(minute // 60, minute % 60), PARIS)
            if all(abs(candidate - other) >= gap for other in taken):
                grid.append(candidate)
                taken.append(candidate)
            minute += int(settings["default_grid_gap_min"])
    notes: list[str] = []
    possible = len(kept_fixed) + len(grid)
    if possible + len(planned) < int(settings["posts_per_day"]):
        notes.append(f"{account['label']} : {possible} créneau(x) possible(s) sur "
                     f"{int(settings['posts_per_day']) - len(planned)} voulus (écart minimal "
                     f"{settings['default_grid_gap_min']} min, jamais de créneau rapproché)")
    slots = [{"slot_at": s.isoformat(), "kind": "fixed", "prime": _is_prime(s, settings)} for s in kept_fixed]
    slots += [{"slot_at": s.isoformat(), "kind": "grid", "prime": _is_prime(s, settings)} for s in grid]
    slots.sort(key=lambda s: datetime.fromisoformat(s["slot_at"]))
    return slots, notes


# ---------------------------------------------------------------- sources, vivier, bonus (R2-R4)


class _World:
    """Ce que le calcul lit : files, sidecars, meta.json, instantane de la veille. Lu une fois par calcul."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.workspace = Path(config.workspace_dir)
        self.output = Path(config.output_dir)
        self.publish_dir = config.section("publish")["state_dir"]
        self.presets_dir = config.section("watch")["presets_dir"]
        self._meta: dict[str, dict[str, Any]] = {}
        self._games: dict[str, str] | None = None
        self._moments: dict[str, dict[int, bool] | None] = {}

    def meta(self, video_id: str) -> dict[str, Any]:
        if video_id not in self._meta:
            data = _read_json(self.workspace / video_id / "meta.json", {})
            if not isinstance(data, dict):
                raise RepartitionError(f"meta.json invalide : {self.workspace / video_id / 'meta.json'}")
            self._meta[video_id] = data
        return self._meta[video_id]

    def veille_games(self) -> dict[str, str]:
        if self._games is None:
            seen = _read_json(Path(str(self.config.section("veille")["state_dir"])) / "seen.json", {})
            queued = seen.get("queued", []) if isinstance(seen, dict) else []
            self._games = {}
            for item in queued if isinstance(queued, list) else []:
                if isinstance(item, dict) and item.get("video_id") and item.get("game_name"):
                    self._games.setdefault(item["video_id"], item["game_name"])
        return self._games

    def source(self, video_id: str) -> dict[str, Any]:
        """``source_key``, ``game_name``, ``source_from`` : meta.json, puis veille, sinon la VOD (jamais le titre)."""
        for origin, name in (("meta", self.meta(video_id).get("game")), ("veille", self.veille_games().get(video_id))):
            if isinstance(name, str) and normalize(name):
                return {"source_key": f"jeu:{normalize(name)}", "game_name": name, "source_from": origin}
        return {"source_key": f"vod:{video_id}", "game_name": None, "source_from": "vod"}

    def exploration(self, video_id: str, clip_id: str, notes: list[str]) -> bool:
        if video_id not in self._moments:
            path = self.workspace / video_id / "moments.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._moments[video_id] = {m["id"]: m.get("exploration") is True for m in data["moments"]}
            except (OSError, ValueError, KeyError, TypeError):
                self._moments[video_id] = None
                notes.append(f"moments.json absent ou illisible pour {video_id} : clip traité comme non exploration")
        moments = self._moments[video_id]
        number = _CLIP_NUMBER.match(clip_id)
        return bool(moments and number and moments.get(int(number[1])))

    def queued_videos(self) -> set[str]:
        queue = _read_json(Path(str(self.config.section("worker")["queue_path"])), [])
        if not isinstance(queue, list):
            raise RepartitionError("file de traitement invalide (une liste est attendue)")
        return {e["video_id"] for e in queue
                if isinstance(e, dict) and e.get("status") in ("waiting", "running") and e.get("video_id")}


def _stats_by_source(world: _World, active: list[dict[str, Any]], now: datetime, settings: dict[str, Any]) -> tuple[
        dict[str, list[float]], list[float]]:
    """Vues reelles des posts releves dans la fenetre, relies a un clip Clipper (``tiktok_post.id``), tous comptes
    confondus : par ``source_key`` et au total. Rien n'est estime (R4)."""
    linked: dict[str, str] = {}
    for path in sorted(world.output.glob("*/*.json")) if world.output.is_dir() else []:
        sidecar = _read_json(path, {})
        post = sidecar.get("tiktok_post") if isinstance(sidecar, dict) else None
        if isinstance(post, dict) and post.get("id"):
            linked[str(post["id"])] = path.parent.name
    since = now - timedelta(days=int(settings["bonus_window_days"]))
    by_source: dict[str, list[float]] = {}
    every: list[float] = []
    seen: set[str] = set()
    for acc in active:
        history = tiktok.read_history(acc["id"], config=world.config)
        for post_id, post in sorted(tiktok.merged_posts(history).items()):
            views, stamp = post.get("views"), post.get("posted_at")
            if post_id in seen or post_id not in linked or isinstance(views, bool) or not isinstance(views, (int, float)):
                continue
            try:
                posted = _paris(datetime.fromisoformat(stamp)) if isinstance(stamp, str) else None
            except ValueError:
                posted = None
            if posted is None or not since <= posted <= now:
                continue
            seen.add(post_id)
            by_source.setdefault(world.source(linked[post_id])["source_key"], []).append(views)
            every.append(views)
    return by_source, every


def _bonus(source_key: str, by_source: dict[str, list[float]], every: list[float], settings: dict[str, Any]) -> tuple[
        float, str]:
    mine = by_source.get(source_key, [])
    if not mine:
        return 0, "no_stats"
    if len(mine) < int(settings["bonus_min_posts"]):
        return 0, "below_min_posts"
    median, reference = statistics.median(mine), statistics.median(every)
    ratio = max(-1.0, min(1.0, median / reference - 1)) if reference > 0 else 0.0
    return (round(float(settings["bonus_points"]) * ratio, 2),
            f"{len(mine)} posts, médiane {_fmt(median)} vues, référence {_fmt(reference)}")


def _pool(world: _World, active: list[dict[str, Any]], settings: dict[str, Any], notes: list[str]) -> tuple[
        list[dict[str, Any]], list[dict[str, str]]]:
    """Clips choisissables (R2) avec les comptes qui peuvent les prendre, et les exclusions comptees par raison."""
    clips: dict[tuple[str, str], dict[str, Any]] = {}
    for acc in active:
        units = publish.available_series_clips(
            None, account=acc["id"], together=False, workspace_dir=world.workspace, output_dir=world.output,
            state_dir=world.publish_dir)
        for unit in units:
            for clip_id in unit["clip_ids"]:
                found = clips.setdefault((unit["video_id"], clip_id), {
                    "video_id": unit["video_id"], "clip_id": clip_id, "style": unit["channel"],
                    "score": unit["score"], "accounts": set()})
                found["accounts"].add(acc["id"])
    excluded_sources = {s.casefold() for s in settings["excluded_sources"]}
    queued = world.queued_videos()
    names = {n.casefold() for c in clips.values() for n in (world.meta(c["video_id"]).get("channel"), c["style"])
             if isinstance(n, str)}
    for source in settings["excluded_sources"]:
        if source.casefold() not in names:
            notes.append(f"{source} : aucune vidéo pour cette source")
    pool: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for key in sorted(clips):
        clip = clips[key]
        sidecar = publish.read_sidecar(world.output, *key)
        own = {n.casefold() for n in (world.meta(key[0]).get("channel"), clip["style"]) if isinstance(n, str)}
        reason = ("multi_part_series" if sidecar.get("part") is not None
                  else "excluded_source" if own & excluded_sources
                  else "in_processing_queue" if key[0] in queued else None)
        if reason:
            excluded.append({"video_id": key[0], "clip_id": key[1], "reason": reason})
        else:
            pool.append(clip)
    return pool, excluded


# ---------------------------------------------------------------- calcul (R1-R7)


def _build(day: date, now: datetime, settings: dict[str, Any], config: Config, computed_by: str) -> dict[str, Any]:
    world = _World(config)
    notes: list[str] = []
    active: list[dict[str, Any]] = []
    for account in accounts.list_accounts(config):
        ready = account["ready_to_publish"] and not account.get("paused_at")
        if account["service"] == "tiktok" and ready:
            active.append(account)
        elif account["service"] != "tiktok" and ready:
            notes.append(f"{account['label']} : compte {accounts.SERVICE_LABELS.get(account['service'], account['service'])}"
                         " prêt, hors périmètre v1 (non planifié)")

    pool, excluded = _pool(world, active, settings, notes)
    by_source, every = _stats_by_source(world, active, now, settings)
    if not every:
        notes.append("aucun relevé récent")
    candidates: list[dict[str, Any]] = []
    for clip in pool:
        source = world.source(clip["video_id"])
        bonus, reason = _bonus(source["source_key"], by_source, every, settings)
        score = clip["score"] if isinstance(clip["score"], (int, float)) and not isinstance(clip["score"], bool) else None
        candidates.append({
            **clip, **source, "score": score, "bonus": bonus, "bonus_reason": reason,
            "adjusted": None if score is None else round(score + bonus, 2),
            "exploration": world.exploration(clip["video_id"], clip["clip_id"], notes)})
    candidates.sort(key=lambda c: (c["adjusted"] is None, -(c["adjusted"] or 0), c["video_id"], c["clip_id"]))

    states: list[dict[str, Any]] = []
    for rank, account in enumerate(active):
        planned_entries = [(n, e) for n, e in publish._account_entries(account["id"], world.publish_dir,
                                                                      world.presets_dir, "config.toml")
                           if (t := _entry_time(e)) is not None and _paris(t).date() == day]
        planned = publish.planned_times(account["id"], state_dir=world.publish_dir, presets_dir=world.presets_dir)
        planned = [t for t in planned if _paris(t).date() == day]
        slots, slot_notes = _account_slots(account, rank, day, settings, planned)
        counts: dict[str, int] = {}
        for _name, entry in planned_entries:
            key = world.source(entry["video_id"])["source_key"]
            counts[key] = counts.get(key, 0) + 1
        order = [s for s in slots if s["prime"]] + [s for s in slots if not s["prime"]]
        states.append({"account": account, "slots": slots, "free": order, "counts": counts, "lines": [],
                       "notes": slot_notes})

    explorations = 0
    remaining = list(candidates)
    progressed = True
    while progressed:
        progressed = False
        for state in states:
            if not state["free"]:
                continue
            for clip in remaining:
                if state["account"]["id"] not in clip["accounts"]:
                    continue
                if state["counts"].get(clip["source_key"], 0) >= int(settings["max_per_source"]):
                    continue
                if clip["exploration"]:
                    off_peak = next((s for s in state["free"] if not s["prime"]), None)
                    if explorations >= int(settings["exploration_per_day"]) or off_peak is None:
                        continue
                    slot = off_peak
                else:
                    slot = state["free"][0]
                state["free"].remove(slot)
                state["counts"][clip["source_key"]] = state["counts"].get(clip["source_key"], 0) + 1
                explorations += 1 if clip["exploration"] else 0
                state["lines"].append({
                    "slot_at": slot["slot_at"], "video_id": clip["video_id"], "clip_id": clip["clip_id"],
                    "score": clip["score"], "bonus": clip["bonus"], "bonus_reason": clip["bonus_reason"],
                    "adjusted": clip["adjusted"], "source_key": clip["source_key"], "game_name": clip["game_name"],
                    "source_from": clip["source_from"], "exploration": clip["exploration"], "prime": slot["prime"]})
                remaining.remove(clip)
                progressed = True
                break

    plan_accounts = []
    for state in states:
        lines = sorted(state["lines"], key=lambda line: datetime.fromisoformat(line["slot_at"]))
        notes_here = list(state["notes"])
        if state["free"]:
            notes_here.append(f"{len(state['free'])} créneau(x) sans clip : vivier insuffisant")
        plan_accounts.append({"account": state["account"]["id"], "label": state["account"]["label"],
                              "slots": state["slots"], "lines": lines, "notes": notes_here})
    return {"day": day.isoformat(), "computed_at": now.isoformat(), "computed_by": computed_by,
            "status": "proposed", "accounts": plan_accounts, "pool": len(pool), "excluded": excluded,
            "notes": notes, "validated_at": None, "created": []}


def _compute_locked(day: date, now: datetime, settings: dict[str, Any], config: Config, computed_by: str,
                    path: Path) -> dict[str, Any]:
    existing = _read_json(path, None)
    if isinstance(existing, dict) and existing.get("status") == "validated":
        raise RepartitionError(f"le plan du {day.isoformat()} est déjà validé : il n'est plus recalculé")
    plan = _build(day, now, settings, config, computed_by)
    channel.atomic_write_json(path, plan)
    return plan


def compute_plan(day: date | str, now: datetime, *, config: Config | None = None,
                 computed_by: str = "worker") -> dict[str, Any]:
    """Calcule le plan de ``day`` (heure de Paris), le remplace dans ``<state_dir>/<jour>.json`` sous verrou et le
    rend. Un plan ``validated`` n'est jamais recalcule (``RepartitionError``). Deterministe hors ``computed_at``."""
    config = config or load_config()
    settings = _settings(config)
    if computed_by not in ("worker", "web"):
        raise RepartitionError(f"computed_by invalide : {computed_by!r} (worker ou web est attendu)")
    target = _as_day(day)
    path = Path(settings["state_dir"]) / f"{target.isoformat()}.json"
    with channel.file_lock(path):
        return _compute_locked(target, now, settings, config, computed_by, path)


def _record_error(path: Path | None, day: date, now: datetime, exc: Exception) -> None:
    """Ecrit l'erreur dans le fichier du jour (l'ecran la montre) et la journalise une seule fois."""
    message = str(exc) or type(exc).__name__
    key = (day.isoformat(), type(exc).__name__, message)
    if key not in _logged_errors:
        _logged_errors.add(key)
        log.warning("répartition du %s : plan non calculé (%s : %s)", day.isoformat(), type(exc).__name__, message)
    if path is None:
        return
    try:
        with channel.file_lock(path):
            current = _read_json(path, None)
            if isinstance(current, dict) and current.get("status") in ("proposed", "validated"):
                return
            channel.atomic_write_json(path, {
                "day": day.isoformat(), "computed_at": now.isoformat(), "computed_by": "worker", "status": "error",
                "error": {"type": type(exc).__name__, "message": message}})
    except (RepartitionError, OSError, ValueError) as write_exc:
        log.warning("répartition du %s : erreur non écrite (%s)", day.isoformat(), write_exc)


def run_if_due(now: datetime, *, config: Config | None = None) -> dict[str, Any] | None:
    """Appelee a chaque tour du worker : calcule le plan de demain (Paris) quand ``compute_time`` est passe et qu'aucun
    plan ``proposed`` ou ``validated`` n'existe. Rend le plan calcule, ``None`` sinon. Une erreur est ecrite dans le
    fichier du jour et journalisee une fois, jamais propagee ; un plan ``proposed`` n'est jamais recalcule seul."""
    config = config or load_config()
    raw = config.section("repartition")
    if raw.get("enabled") is False:
        return None
    local = _paris(now)
    day = local.date() + timedelta(days=1)
    path = Path(str(raw["state_dir"])) / f"{day.isoformat()}.json" if isinstance(raw.get("state_dir"), str) else None
    try:
        settings = _settings(config)
        if local.hour * 60 + local.minute < _minutes(settings, "compute_time"):
            return None
        with channel.file_lock(path):
            existing = _read_json(path, None)
            if isinstance(existing, dict):
                if existing.get("status") in ("proposed", "validated"):
                    return None
                stamp = existing.get("computed_at")
                if existing.get("status") == "error" and isinstance(stamp, str) and now - datetime.fromisoformat(
                        stamp) < _ERROR_RETRY:
                    return None
            return _compute_locked(day, now, settings, config, "worker", path)
    except (RepartitionError, *_HANDLED) as exc:
        _record_error(path, day, now, exc)
        return None
