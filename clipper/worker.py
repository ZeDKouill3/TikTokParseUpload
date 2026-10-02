"""Worker separe du serveur HTTP (ADR-35b7 §1) : boucle sur la file
``state/queue.json`` (SPEC-74e9 §2) et lance chaque video dans un processus
enfant ``python -m clipper <action> <url|id>``, un seul a la fois
(ADR-fb9b). N'importe que clipper.pipeline, clipper.channel et
clipper.config : jamais clipper.web, jamais une etape (ADR-b16b). Il pousse aussi
les publications dues de state/publish/<chaine>.json vers TikTok, une a la fois
(SPEC-9225 R3), par clipper.tiktok (ADR-1a58) : seul module qui parle a TikTok.

Entree de file (SPEC-74e9 §2.1) : {id, video_id, url, channel | null,
action ("run" | "render"), force_steps, enqueued_at, status ("waiting" |
"running"), pid | null}.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from clipper import accounts as accounts_mod
from clipper import browser
from clipper import channel as channel_mod
from clipper import publish as publish_mod
from clipper import tiktok
from clipper.config import Config, ConfigError, load_config

log = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    "poll_interval_s": 2,
    "cancel_grace_s": 10,
    "queue_path": "state/queue.json",
    # Battement du worker (voyant « worker actif / arrêté » de l'interface web) :
    # fichier d'état {pid, at} (worker.json, à côté de la file) réécrit au plus
    # toutes les heartbeat_interval_s secondes ; l'interface le juge périmé après
    # trois intervalles sans battement.
    "heartbeat_interval_s": 5,
}

WORKER_COMMAND = "python -m clipper worker"
HEARTBEAT_FILE = "worker.json"
_STALE_AFTER_BEATS = 3

_CANCEL_REASON = "annulée par l'utilisateur"
LOG_FILE = "worker.log"
_LOG_TAIL_LINES = 20
_LOG_TAIL_CHARS = 2000


def log_path(video_id: str, config: Config) -> Path:
    """Journal de la sortie (stdout + stderr) du processus enfant d'une vidéo :
    ``workspace/<video_id>/worker.log``, réécrit à chaque lancement."""
    return Path(config.workspace_dir) / video_id / LOG_FILE


def _log_tail(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(journal illisible : {exc})"
    tail = "\n".join(text.strip().splitlines()[-_LOG_TAIL_LINES:])[-_LOG_TAIL_CHARS:]
    return tail or "(aucune sortie)"


def heartbeat_path(config: Config) -> Path:
    return _queue_path(config).with_name(HEARTBEAT_FILE)


def read_heartbeat(config: Config, now: datetime | None = None) -> dict[str, Any]:
    """État du worker d'après son battement : ``active`` (battement récent, pid
    vivant), ``stale`` (battement périmé : plus de trois intervalles) ou
    ``stopped`` (aucun battement, ou pid mort). Toujours la commande pour le
    lancer. Un fichier illisible lève ``WorkerError`` : jamais un état inventé."""
    section = config.section("worker")
    path = heartbeat_path(config)
    out: dict[str, Any] = {"command": WORKER_COMMAND, "pid": None, "at": None, "age_s": None}
    if not path.is_file():
        return {**out, "state": "stopped", "reason": f"aucun battement ({path}) : le worker n'a jamais tourné ici"}
    try:
        beat = json.loads(path.read_text(encoding="utf-8"))
        pid, at = int(beat["pid"]), datetime.fromisoformat(beat["at"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise WorkerError(f"battement du worker illisible ({path}) : {exc}") from exc
    if at.tzinfo is None:
        raise WorkerError(f"battement du worker illisible ({path}) : horodatage sans fuseau")
    age = (now or datetime.now(timezone.utc)) - at
    age_s = age.total_seconds()
    out.update(pid=pid, at=beat["at"], age_s=age_s)
    if not _pid_alive(pid):
        return {**out, "state": "stopped", "reason": f"le processus {pid} du worker n'existe plus"}
    if age_s > float(section["heartbeat_interval_s"]) * _STALE_AFTER_BEATS:
        return {**out, "state": "stale", "reason": f"battement périmé : dernier il y a {int(age_s)} s"}
    return {**out, "state": "active", "reason": None}


class WorkerError(Exception):
    """Operation de file impossible en l'etat : entree inconnue, doublon en
    attente."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _queue_path(config: Config) -> Path:
    return Path(config.section("worker")["queue_path"])


def _read_queue(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_queue(path: Path, entries: list[dict[str, Any]]) -> None:
    channel_mod.atomic_write_json(path, entries)


def _locked(path: Path):
    """Verrou inter-processus sur la file : tout cycle lecture-modification-
    ecriture de state/queue.json se fait dedans (le worker et l'API web sont
    deux processus, ADR-35b7)."""
    return channel_mod.file_lock(path)


def enqueue(
    url: str,
    channel: str | None,
    action: str,
    force_steps: list[str] | None = None,
    *,
    config: Config | None = None,
) -> dict[str, Any]:
    """Ajoute une entree a la file (SPEC-74e9 §2.1), ecriture atomique.
    ``url`` est l'URL source pour ``action="run"``, le video_id pour
    ``action="render"`` (deja lance, pas d'URL a resoudre). Refuse un
    doublon deja ``waiting`` pour le meme video_id et la meme action
    (SPEC-74e9 §2.2)."""
    if action == "run":
        # clipper.download est une etape (ADR-b16b) : le worker n'importe
        # que clipper.pipeline, qui l'importe deja pour l'enchainement des
        # etapes (extract_video_id est un simple parsing d'URL, aucun
        # reseau).
        from clipper import pipeline

        video_id = pipeline.download.extract_video_id(url)
    else:
        video_id = url

    config = config or load_config()
    path = _queue_path(config)
    entry = {
        "id": uuid.uuid4().hex,
        "video_id": video_id,
        "url": url,
        "channel": channel,
        "action": action,
        "force_steps": list(force_steps or []),
        "enqueued_at": _now_iso(),
        "status": "waiting",
        "pid": None,
    }
    with _locked(path):
        entries = _read_queue(path)
        for existing in entries:
            if existing["video_id"] == video_id and existing["action"] == action and existing["status"] == "waiting":
                raise WorkerError(f"deja en file d'attente : {video_id} ({action})")
        entries.append(entry)
        _write_queue(path, entries)
    return entry


def move_to_front(video_id: str, *, config: Config | None = None) -> None:
    """Passe l'entree ``waiting`` de ``video_id`` en tete des entrees en
    attente, sans toucher l'entree ``running`` (SPEC-74e9 §2.2)."""
    config = config or load_config()
    path = _queue_path(config)
    with _locked(path):
        entries = _read_queue(path)

        running = None
        target = None
        rest: list[dict[str, Any]] = []
        for entry in entries:
            if entry["status"] == "running":
                running = entry
            elif target is None and entry["video_id"] == video_id and entry["status"] == "waiting":
                target = entry
            else:
                rest.append(entry)

        if target is None:
            raise WorkerError(f"aucune entree en attente pour {video_id!r}")

        reordered = ([running] if running is not None else []) + [target] + rest
        _write_queue(path, reordered)


def remove(video_id: str, *, config: Config | None = None) -> None:
    """Retire l'entree ``waiting`` de ``video_id``, sans toucher l'entree
    ``running`` (SPEC-74e9 §2.2)."""
    config = config or load_config()
    path = _queue_path(config)
    with _locked(path):
        entries = _read_queue(path)
        remaining = [e for e in entries if not (e["video_id"] == video_id and e["status"] == "waiting")]
        if len(remaining) == len(entries):
            raise WorkerError(f"aucune entree en attente pour {video_id!r}")
        _write_queue(path, remaining)


_STILL_ACTIVE = 259


def _pid_alive(pid: int | None) -> bool:
    """Un pid dont le processus a deja quitte (mort avant le redemarrage du
    worker) doit etre detecte meme si le handle du kernel Windows vit
    encore (ex. un Popen non ferme dans le meme processus python) :
    OpenProcess reussit alors, seul GetExitCodeProcess dit si c'est
    STILL_ACTIVE."""
    if pid is None:
        return False
    if sys.platform == "win32":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and exit_code.value == _STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _build_command(entry: dict[str, Any]) -> list[str]:
    # --config est une option globale du parseur : avant la sous-commande.
    cmd = [sys.executable, "-m", "clipper"]
    if entry.get("channel"):
        cmd += ["--config", f"presets/{entry['channel']}.toml"]
    cmd += [entry["action"], entry["url"] if entry["action"] == "run" else entry["video_id"]]
    for step in entry.get("force_steps") or []:
        cmd += ["--force-step", step]
    return cmd


class Worker:
    """Boucle sur ``state/queue.json``, un enfant a la fois (ADR-fb9b).
    ``spawner`` (defaut ``subprocess.Popen``) est injecte dans les tests."""

    def __init__(
        self,
        *,
        config: Config | None = None,
        spawner: Callable[[list[str]], Any] | None = None,
        watch_lister: Callable[[str], list[dict[str, Any]]] | None = None,
        publisher: Callable[..., dict[str, Any]] | None = None,
        stats_fetcher: Callable[..., dict[str, Any]] | None = None,
        login_checker: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._popen = None
        if spawner is None:
            import subprocess

            self._popen = subprocess.Popen
        self.config = config or load_config()
        self.spawner = spawner
        self._log_handle: Any | None = None
        self._launched_at: datetime | None = None
        self.watch_lister = watch_lister
        self._logged_watch_errors: set[str] = set()
        self.publisher = publisher or tiktok.publish
        self._logged_publish_errors: set[str] = set()
        self.stats_fetcher = stats_fetcher or tiktok.fetch_stats
        self.login_checker = login_checker or browser.login_state  # connexion verifiee avant chaque publication
        self._stats_attempts: dict[str, datetime] = {}
        self._logged_stats_errors: set[str] = set()
        self._path = _queue_path(self.config)
        self._process: Any | None = None
        self._entry: dict[str, Any] | None = None
        self._last_beat: float | None = None
        self._recover_orphans()
        self._recover_interrupted_publications()

    def _recover_interrupted_publications(self) -> None:
        """Une publication restee « en cours » d'un worker arrete en plein pilotage devient un echec explicite
        et reessayable (SPEC-1ed3 R5), jamais bloquee en « en cours »."""
        try:
            watch = self.config.section("watch")
            state_dir = self.config.section("publish")["state_dir"]
            for name in [*channel_mod.list_channels(watch["presets_dir"]), publish_mod.NO_CHANNEL]:
                if publish_mod.fail_interrupted(name, state_dir=state_dir):
                    log.warning("%s : publication interrompue par l'arrêt du worker, passée en échec", name)
        except (publish_mod.PublishError, channel_mod.ChannelError, ConfigError, OSError, ValueError) as exc:
            log.error("reprise des publications interrompues impossible : %s", exc)

    def _beat(self) -> None:
        """Écrit ``{pid, at}`` dans ``heartbeat_path`` si ``heartbeat_interval_s``
        s'est écoulé depuis le dernier battement (écriture atomique)."""
        section = self.config.section("worker")
        now = time.monotonic()
        if self._last_beat is not None and now - self._last_beat < float(section["heartbeat_interval_s"]):
            return
        path = heartbeat_path(self.config)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        os.replace(tmp, path)
        self._last_beat = now

    def _recover_orphans(self) -> None:
        """Au demarrage, une entree ``running`` dont le pid est mort
        (worker precedent tombe) repasse ``waiting`` en tete (SPEC-74e9
        §2.4). Une seule entree ``running`` possible a la fois."""
        with _locked(self._path):
            entries = _read_queue(self._path)
            for i, entry in enumerate(entries):
                if entry["status"] == "running":
                    if not _pid_alive(entry["pid"]):
                        entry["status"] = "waiting"
                        entry["pid"] = None
                        entries.pop(i)
                        entries.insert(0, entry)
                        _write_queue(self._path, entries)
                    break

    def tick(self) -> None:
        """Une iteration : termine l'entree si l'enfant courant a fini,
        sinon lance la tete de file si aucun enfant ne vit, sinon reprend
        les videos ``queued`` dont ``retry_at`` est passe (SPEC-74e9
        §2.3-2.4). La surveillance des chaines echues passe d'abord, enfant
        en cours ou non (SPEC-74e9 §5.1). Chaque itération bat d'abord (voyant
        de l'interface web)."""
        self._beat()
        self._watch_channels()
        if not self._publish_due():
            self._stats_due()

        if self._process is not None:
            if self._process.poll() is None:
                return
            self._finish_current()

        if self._launch_head():
            return

        from clipper import pipeline

        pipeline.process_queue(config=self.config)

    def _watch_channels(self) -> None:
        """Appelle ``watch.check`` pour chaque chaine ``watch = true`` dont
        ``checked_at + watch_interval_s`` est passe. Un preset ou un etat
        illisible est journalise une fois (ADR-ad2e : jamais ignore en
        silence) et ne tue pas le worker."""
        from clipper import watch

        section = self.config.section("watch")
        now = datetime.now(timezone.utc)
        try:
            names = channel_mod.list_channels(section["presets_dir"])
            for name in names:
                _config, settings = channel_mod.load_channel(
                    name, presets_dir=section["presets_dir"], base=section["base_config"])
                if not settings["watch"]:
                    continue
                if watch.is_due(name, settings["watch_interval_s"], now, config=self.config):
                    watch.check(name, now, lister=self.watch_lister, config=self.config)
        except (channel_mod.ChannelError, ConfigError, watch.WatchError) as exc:
            message = str(exc)
            if message not in self._logged_watch_errors:
                self._logged_watch_errors.add(message)
                log.error("surveillance des chaines impossible : %s", message)

    # ------------------------------------------------------------ publication TikTok

    def _publish_due(self) -> bool:
        """Une publication TikTok due par iteration (SPEC-9225 R3) ; vrai si une tentative a eu lieu.
        Une file, un preset ou un reglage illisible est journalise une fois (ADR-ad2e) et ne tue
        pas le worker."""
        try:
            return self._publish_next()
        except (publish_mod.PublishError, channel_mod.ChannelError, ConfigError, tiktok.TikTokError) as exc:
            message = str(exc)
            if message not in self._logged_publish_errors:
                self._logged_publish_errors.add(message)
                log.error("publication TikTok impossible : %s", message)
        return False

    def _stats_due(self) -> None:
        """Releve periodique des statistiques (SPEC-47e2 R4) : coupe quand ``stats_interval_h`` vaut 0 (defaut :
        le releve se fait a l'usage, pas en fond) ; sinon un compte par iteration, jamais dans l'iteration
        qui a pilote une publication (un seul pilotage du navigateur a la fois), seulement pour un compte
        « pret a publier » (donc ni deconnecte ni arrete par R4 de SPEC-9225). La liste des posts vient de TikTok :
        un compte sans clip publie par Clipper est releve aussi. Un echec est journalise une fois et n'est pas
        retente avant ``stats_interval_h`` (ADR-ad2e : jamais silencieux, jamais en boucle)."""
        now = datetime.now(timezone.utc)
        try:
            settings = tiktok.get_settings(self.config)
            watch = self.config.section("watch")
            scope = {"state_dir": self.config.section("publish")["state_dir"],
                     "presets_dir": watch["presets_dir"], "base": watch["base_config"]}
            if float(settings["stats_interval_h"]) == 0:
                return
            wait = timedelta(hours=float(settings["stats_interval_h"]))
            for found in accounts_mod.list_accounts(self.config):
                account = found["id"]
                if not found["ready_to_publish"]:
                    continue
                tried = self._stats_attempts.get(account)
                if tried is not None and now - tried < wait:
                    continue
                if publish_mod.halted_account(account, **scope) is not None:
                    continue
                if not tiktok.stats_due(account, config=self.config, now=now):
                    continue
                self._stats_attempts[account] = now
                self.stats_fetcher(account, config=self.config, on_tick=self._beat)
                log.info("%s : statistiques TikTok relevées", account)
                return
        except Exception as exc:  # noqa: BLE001 - jamais un worker mort : l'echec est journalise une fois
            message = f"{type(exc).__name__} : {exc}" if not isinstance(
                exc, (tiktok.TikTokError, browser.BrowserError, publish_mod.PublishError, channel_mod.ChannelError,
                      accounts_mod.AccountsError, ConfigError)) else str(exc)
            if message not in self._logged_stats_errors:
                self._logged_stats_errors.add(message)
                log.error("relevé des statistiques TikTok impossible : %s", message)

    def _publish_next(self) -> bool:
        now = datetime.now(timezone.utc)
        settings = tiktok.get_settings(self.config)
        watch = self.config.section("watch")
        paths = {"state_dir": self.config.section("publish")["state_dir"],
                 "presets_dir": watch["presets_dir"], "base": watch["base_config"]}
        due = []
        # la file des videos sans chaine (SPEC-1ed3 R3) est lue comme celle d'une chaine sans creneau ni compte
        for name in [*channel_mod.list_channels(paths["presets_dir"]), publish_mod.NO_CHANNEL]:
            channel = publish_mod.channel_settings(name, paths["presets_dir"], paths["base"])
            for entry in publish_mod.list_entries(name, state_dir=paths["state_dir"]):
                if entry["status"] != "scheduled" or not entry["slot_at"]:
                    continue
                slot = datetime.fromisoformat(entry["slot_at"])
                mode = entry.get("publish_mode") or str(settings["publish_mode"])
                window = timedelta(days=float(settings["schedule_max_days"])) if mode == "scheduled" else timedelta(0)
                if slot - window <= now:  # immediat : creneau atteint ; programme : date dans la fenetre TikTok
                    due.append((slot, name, channel, entry, mode))
        due.sort(key=lambda d: (d[0], d[1], d[3]["clip_id"]))
        for slot, name, channel, entry, mode in due:
            if self._publish_one(slot, name, channel, entry, mode, settings, paths, now):
                return True
        return False

    def _publish_one(self, slot: datetime, name: str, channel: dict[str, Any], entry: dict[str, Any], mode: str,
                     settings: dict[str, Any], paths: dict[str, Any], now: datetime) -> bool:
        """Vrai si la tentative de publication a eu lieu (reussie ou en echec) : fin de l'iteration."""
        video_id, clip_id = entry["video_id"], entry["clip_id"]
        account = publish_mod.entry_account(entry, channel["tiktok_account"])  # jamais un autre compte en repli
        where = {"channel": name, "video_id": video_id, "clip_id": clip_id}
        if not account:
            self._fail(entry, name, f"chaîne {name} sans compte TikTok relié : renseigne [channel] tiktok_account "
                       "dans son preset" if name != publish_mod.NO_CHANNEL else
                       "aucun compte de publication choisi : modifie la publication et choisis un compte prêt à publier",
                       halted=False, account=None, state_dir=paths["state_dir"])
            return False
        if not self._account_ready(entry, name, account, paths["state_dir"]):
            return False
        scope = {"state_dir": paths["state_dir"], "presets_dir": paths["presets_dir"], "base": paths["base"]}
        if publish_mod.halted_account(account, **scope) is not None:
            return False  # arret sur en cours (R4) : rien ne part avant « Reessayer »

        times = publish_mod.account_publish_times(account, **scope)
        tz = ZoneInfo(str(channel["timezone"]))
        blocked = tiktok.check_limits(times, slot if mode == "scheduled" else now, settings, tz)
        if blocked is not None and entry.get("manual"):
            # publication pilotee depuis l'ecran Publication : le plafond a deja ete verifie au formulaire ; s'il
            # est depasse depuis, l'entree attend avec la raison, jamais reportee ni deplacee (SPEC-1ed3 R4)
            self._wait(entry, name, account, f"{blocked} : la publication attend, modifie son heure ou annule-la",
                       paths["state_dir"])
            return False
        if blocked is not None:
            moved = publish_mod.postpone(
                video_id, clip_id, name, blocked, now=now,
                allowed=lambda candidate: tiktok.check_limits(times, candidate, settings, tz), **scope)
            log.warning("%s/%s : %s", video_id, clip_id, moved["postponed_reason"])
            tiktok.emit_event({"level": "warn", "account": account, **where, "reason": moved["postponed_reason"],
                               "capture": None}, config=self.config)
            return False

        if not self._connected(entry, name, account, paths["state_dir"]):
            return False
        if entry.get("waiting_reason"):
            publish_mod.set_waiting_reason(video_id, clip_id, name, None, state_dir=paths["state_dir"])
        try:
            clip = tiktok.clip_payload(publish_mod.read_sidecar(self.config.output_dir, video_id, clip_id),
                                       self.config.output_dir)
            extra = {"options": entry["post_options"]} if entry.get("post_options") else {}
            publish_mod.mark_in_progress(video_id, clip_id, name, state_dir=paths["state_dir"])
            result = self.publisher(clip, account, mode=mode, schedule_at=slot if mode == "scheduled" else None,
                                    config=self.config, on_tick=self._beat, **extra)
        except tiktok.TikTokStop as stop:
            self._fail(entry, name, stop.reason, halted=True, account=account, capture=stop.capture,
                       state_dir=paths["state_dir"])
        except browser.BrowserError as exc:
            self._fail(entry, name, str(exc), halted=True, account=account, state_dir=paths["state_dir"])
        except (tiktok.TikTokError, publish_mod.PublishError) as exc:
            self._fail(entry, name, str(exc), halted=False, account=account, state_dir=paths["state_dir"])
        except Exception as exc:  # noqa: BLE001 - jamais un worker mort : l'entree echoue, avec la raison
            log.exception("%s/%s : erreur inattendue pendant la publication", video_id, clip_id)
            self._fail(entry, name, f"erreur inattendue : {type(exc).__name__} : {exc}", halted=True,
                       account=account, state_dir=paths["state_dir"])
        else:
            publish_mod.mark_published(
                video_id, clip_id, name, state_dir=paths["state_dir"], output_dir=self.config.output_dir,
                tiktok_state=result["state"], post_url=result["post_url"], post_id=result["post_id"],
                publish_at=result["publish_at"], post_note=result["note"], account=account)
            label = "programmée sur TikTok" if result["state"] == "scheduled_on_tiktok" else "publiée"
            log.info("%s/%s : %s (%s)", video_id, clip_id, label, result["post_url"] or result["note"])
            tiktok.emit_event({"level": "info", "account": account, **where,
                               "reason": f"{label} : {result['post_url'] or result['note']}", "capture": None},
                              config=self.config)
        return True

    def _wait(self, entry: dict[str, Any], channel: str, account: str, reason: str, state_dir: str | Path) -> None:
        """Entree non tentee (SPEC-00d1 R4) : elle reste ``scheduled`` avec la raison visible ; journal et
        evenement console une seule fois par raison."""
        if publish_mod.set_waiting_reason(entry["video_id"], entry["clip_id"], channel, reason, state_dir=state_dir):
            log.warning("%s/%s : publication en attente : %s", entry["video_id"], entry["clip_id"], reason)
            tiktok.emit_event({"level": "warn", "account": account, "channel": channel, "video_id": entry["video_id"],
                               "clip_id": entry["clip_id"], "reason": reason, "capture": None}, config=self.config)

    def _account_ready(self, entry: dict[str, Any], channel: str, account: str, state_dir: str | Path) -> bool:
        """Le compte de l'entree est-il « pret a publier » (R3, R4) ? Sinon l'entree n'est pas tentee."""
        known = {a["id"]: a for a in accounts_mod.list_accounts(self.config)}
        found = known.get(account)
        if found is None:
            reason = f"compte {account} introuvable dans l'écran Comptes : choisis un autre compte pour cette publication"
        elif not found["ready_to_publish"]:
            why = f" ({found['ready_note']})" if found.get("ready_note") else ""
            label = found["label"] or account
            reason = (f"compte {label} non prêt à publier{why} : Comptes > {label} > J'ai réglé le problème "
                      "(la case « prêt à publier » est automatique), ou choisis un autre compte")
        else:
            return True
        self._wait(entry, channel, account, reason, state_dir)
        return False

    def _connected(self, entry: dict[str, Any], channel: str, account: str, state_dir: str | Path) -> bool:
        """Connexion TikTok du profil verifiee avant chaque publication (R2) ; une session expiree decoche
        « pret a publier » (R3) et l'entree reste en attente avec la raison."""
        try:
            observed = self.login_checker(account, config=self.config)
            result = accounts_mod.record_login(self.config, account, observed)
        except (browser.BrowserError, accounts_mod.AccountsError) as exc:
            self._wait(entry, channel, account, f"connexion du compte {account} non vérifiable : {exc}", state_dir)
            return False
        if result["login"]["state"] == "connected":
            return True
        reason = f"compte {account} non connecté à TikTok : {accounts_mod.ready_blocked_reason(result)}"
        if result["auto_unchecked"]:
            reason += " (« prêt à publier » décoché)"
        self._wait(entry, channel, account, reason, state_dir)
        return False

    def _fail(self, entry: dict[str, Any], channel: str, reason: str, *, halted: bool, account: str | None,
              state_dir: str | Path, capture: Path | None = None) -> None:
        """Entree ``failed`` (reessayable), journal et evenement console (SPEC-9225 R4). Un arret R4 decoche
        aussi « pret a publier » du compte, jusqu'a ce que l'utilisateur le recoche (SPEC-00d1 R3)."""
        video_id, clip_id = entry["video_id"], entry["clip_id"]
        log.error("%s/%s : publication TikTok en échec : %s", video_id, clip_id, reason)
        publish_mod.mark_failed(video_id, clip_id, channel, reason, capture=capture, halted=halted, state_dir=state_dir)
        if halted and account:
            try:
                accounts_mod.uncheck_ready(self.config, account, f"arrêt de publication : {reason}")
            except accounts_mod.AccountsError as exc:
                log.error("compte %s : « prêt à publier » non décoché : %s", account, exc)
        tiktok.emit_event({"level": "error", "account": account, "channel": channel, "video_id": video_id,
                           "clip_id": clip_id, "reason": reason, "capture": str(capture) if capture else None},
                          config=self.config)

    def _launch_head(self) -> bool:
        """Lance la tete de file ``waiting`` ; le cycle relecture-lancement-
        ecriture est sous verrou, la file ayant pu changer (API web) depuis
        le dernier tick. Faux si rien n'attend."""
        with _locked(self._path):
            entries = _read_queue(self._path)
            entry = next((e for e in entries if e["status"] == "waiting"), None)
            if entry is None:
                return False
            self._launched_at = datetime.now(timezone.utc)
            process = self._spawn(entry, _build_command(entry))
            entry["status"] = "running"
            entry["pid"] = process.pid
            _write_queue(self._path, entries)
        self._process = process
        self._entry = entry
        return True

    def _spawn(self, entry: dict[str, Any], cmd: list[str]) -> Any:
        if self.spawner is not None:
            return self.spawner(cmd)
        return self._popen_logged(entry, cmd)

    def _popen_logged(self, entry: dict[str, Any], cmd: list[str]) -> Any:
        """Lance l'enfant avec stdout et stderr dans son journal (jamais perdus)."""
        import subprocess

        path = log_path(entry["video_id"], self.config)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "wb")
        try:
            process = self._popen(cmd, stdout=handle, stderr=subprocess.STDOUT)
        except BaseException:
            handle.close()
            raise
        self._log_handle = handle
        return process

    def _close_log(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _record_child_failure(self, entry: dict[str, Any], code: int) -> None:
        """L'enfant a quitté avec un code non nul : la vidéo passe ``failed`` dans
        ``pipeline.json`` (créé au besoin) avec le code et la fin du journal, sauf
        si l'enfant a lui-même écrit son échec (failed/queued) depuis son lancement
        (ADR-ad2e : jamais une disparition silencieuse)."""
        from clipper import pipeline

        video_id = entry["video_id"]
        try:
            state = pipeline.load_state(video_id, config=self.config)
        except pipeline.PipelineError:
            state = pipeline.new_state(video_id, entry["url"], self.config.mode, channel=entry.get("channel"))
        else:
            written = state.get("updated_at")
            if (state.get("status") in ("failed", "queued") and written
                    and datetime.fromisoformat(written) >= self._launched_at):
                log.error("%s : processus enfant terminé avec le code %s (état écrit par l'enfant conservé)", video_id, code)
                return
        path = log_path(video_id, self.config)
        reason = f"le processus enfant s'est terminé avec le code {code} (journal : {path}) : {_log_tail(path)}"
        state.pop("dismissed_at", None)
        state.update(status="failed", reason=reason, retry_at=None)
        pipeline.save_state(state, config=self.config)
        log.error("%s : %s", video_id, reason)

    def _finish_current(self) -> None:
        entry = self._entry
        video_id = entry["video_id"]
        self._close_log()
        code = self._process.poll()
        try:
            if code:
                self._record_child_failure(entry, code)
        finally:
            with _locked(self._path):
                entries = _read_queue(self._path)
                entries = [e for e in entries if not (e["video_id"] == video_id and e["status"] == "running")]
                _write_queue(self._path, entries)
            self._process = None
            self._entry = None

    def _terminate_process(self) -> None:
        self._process.terminate()
        grace = float(self.config.section("worker")["cancel_grace_s"])
        deadline = time.monotonic() + grace
        while self._process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if self._process.poll() is None:
            self._process.kill()

    def cancel(self, video_id: str) -> None:
        """Termine l'enfant en cours pour ``video_id`` et fait passer
        ``pipeline.json`` en ``failed`` (SPEC-74e9 §2.3)."""
        entries = _read_queue(self._path)
        entry = next((e for e in entries if e["video_id"] == video_id and e["status"] == "running"), None)
        if entry is None:
            raise WorkerError(f"aucune video en cours pour {video_id!r}")

        self._terminate_process()
        with _locked(self._path):
            entries = [e for e in _read_queue(self._path) if e["id"] != entry["id"]]
            _write_queue(self._path, entries)
        self._process = None
        self._entry = None

        from clipper import pipeline

        state = pipeline.load_state(video_id, config=self.config)
        state.update(status="failed", reason=_CANCEL_REASON, retry_at=None)
        pipeline.save_state(state, config=self.config)

    def loop(self) -> None:
        """Boucle jusqu'a interruption, a l'intervalle ``poll_interval_s``
        de CONFIG_DEFAULTS (SPEC-74e9 §2.3)."""
        interval = float(self.config.section("worker")["poll_interval_s"])
        while True:
            self.tick()
            time.sleep(interval)
