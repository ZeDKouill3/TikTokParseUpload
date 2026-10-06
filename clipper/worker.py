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
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import tomllib

from clipper import accounts as accounts_mod
from clipper import browser, network
from clipper import channel as channel_mod
from clipper import publish as publish_mod
from clipper import tiktok, youtube
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
    short_clips: bool | None = None,
) -> dict[str, Any]:
    """Ajoute une entree a la file (SPEC-74e9 §2.1), ecriture atomique.
    ``short_clips`` (TASK-4f5e) : choix de la video pour les clips courts ;
    None = non precise, l'entree n'a alors pas le champ (valeur du style).
    ``url`` est l'URL source pour ``action="run"``, le video_id pour
    ``action="render"`` (deja lance, pas d'URL a resoudre). Refuse un
    doublon deja ``waiting`` pour le meme video_id et la meme action
    (SPEC-74e9 §2.2)."""
    if short_clips is not None and not isinstance(short_clips, bool):
        raise WorkerError(f"short_clips invalide : {short_clips!r} (attendu : true ou false)")
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
        **({} if short_clips is None else {"short_clips": short_clips}),
    }
    with _locked(path):
        entries = _read_queue(path)
        for existing in entries:
            if existing["video_id"] == video_id and existing["action"] == action and existing["status"] == "waiting":
                raise WorkerError(f"deja en file d'attente : {video_id} ({action})")
        entries.append(entry)
        _write_queue(path, entries)
    if action == "run":
        _start_thumbnail_fetch(url, config)
    return entry


def _start_thumbnail_fetch(url: str, config: Config) -> threading.Thread | None:
    """URL non YouTube : recupere la miniature (metadonnees yt-dlp, sans telecharger) dans un fil
    d'arriere-plan qui ne bloque pas l'ajout. Un echec est journalise, jamais une miniature inventee."""
    from clipper import pipeline

    download = pipeline.download
    if download.is_youtube_url(url):
        return None

    def run() -> None:
        try:
            download.fetch_thumbnail(url, config.workspace_dir)
        except Exception:
            log.exception("miniature indisponible pour %s", url)

    thread = threading.Thread(target=run, name="thumbnail-fetch", daemon=True)
    thread.start()
    return thread


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


_INTERRUPTED_REASON = "interrompue"


def _live_in_queue(video_id: str, config: Config) -> bool:
    """Vrai si la file a une entrée ``running`` pour ``video_id`` dont le processus existe encore."""
    entries = _read_queue(_queue_path(config))  # lecture seule : l'ecriture de la file est atomique
    return any(e["video_id"] == video_id and e["status"] == "running" and _pid_alive(e.get("pid")) for e in entries)


def _worker_busy_inline(config: Config) -> bool:
    """Vrai si le worker est vivant et reprend lui-même des vidéos en file (battement ``busy``) : leur étape
    ``running`` n'a alors pas d'entrée dans la file sans être orpheline."""
    path = heartbeat_path(config)
    try:
        beat = json.loads(path.read_text(encoding="utf-8"))
        return bool(beat.get("busy")) and _pid_alive(int(beat["pid"]))
    except FileNotFoundError:
        return False
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise WorkerError(f"battement du worker illisible ({path}) : {exc}") from exc


def is_interrupted(state: dict[str, Any], config: Config) -> bool:
    """Une vidéo ``running`` dont aucun processus ne travaille (pas d'entrée ``running`` vivante dans la file, et
    le worker n'est pas en train de la reprendre lui-même) est interrompue : serveur ou PC arrêté en plein
    traitement (TASK-bdd5)."""
    if state.get("status") != "running":
        return False
    return not _live_in_queue(state["video_id"], config) and not _worker_busy_inline(config)


def mark_interrupted(video_id: str, config: Config, *, cancelled: bool = False) -> str | None:
    """Étape orpheline ``running`` -> ``pending`` (les étapes terminées restent ``done``), vidéo ``failed`` avec
    ``reason``, journalisé. Renvoie l'étape interrompue (None si aucune)."""
    from clipper import pipeline

    state = pipeline.load_state(video_id, config=config)
    orphan = next((n for n, st in state["steps"].items() if st.get("status") == "running"), None)
    if orphan is not None:
        state["steps"][orphan].update(status="pending", reason=None, started_at=None, finished_at=None, progress=None)
    detail = f"{_INTERRUPTED_REASON} à l'étape {orphan}" if orphan else _INTERRUPTED_REASON
    state.update(status="failed", reason=f"{_CANCEL_REASON} ({detail})" if cancelled else detail, retry_at=None)
    pipeline.save_state(state, config=config)
    log.warning("%s : traitement interrompu (%s), plus aucun processus ne travaille dessus", video_id, detail)
    return orphan


def resume(video_id: str, *, config: Config | None = None) -> dict[str, Any]:
    """Remet une vidéo interrompue dans la file ; elle repart de sa première étape non terminée (les étapes
    ``done`` ne sont pas refaites, ADR-b16b). Avant la revue : ``run`` sur l'URL source ; à partir de la revue :
    ``render``."""
    from clipper import pipeline

    config = config or load_config()
    state = pipeline.load_state(video_id, config=config)
    if state.get("status") == "running" and not is_interrupted(state, config):
        raise WorkerError(f"{video_id} est en cours de traitement : rien à reprendre")
    first = next((n for n in pipeline.STEPS if state["steps"][n]["status"] != "done"), None)
    if first is None:
        raise WorkerError(f"{video_id} : toutes les étapes sont terminées, rien à reprendre")
    if pipeline.STEPS.index(first) >= pipeline.STEPS.index(pipeline._AFTER_REVIEW):
        action, target = "render", video_id
    else:
        if not state.get("source_url"):
            raise WorkerError(f"{video_id} : pipeline.json sans source_url, impossible de reprendre à l'étape {first}")
        action, target = "run", state["source_url"]
    if state.get("status") == "running":
        mark_interrupted(video_id, config)
    state = pipeline.load_state(video_id, config=config)
    state.pop("dismissed_at", None)
    pipeline.save_state(state, config=config)
    return enqueue(target, state.get("channel"), action, config=config)


def cancel(video_id: str, *, config: Config | None = None) -> None:
    """Annule la video en cours (SPEC-74e9 §2.3) depuis n'importe quel processus (API web), sans construire de
    ``Worker`` : l'enfant est arrete par le pid lu dans la file (``cancel_grace_s`` puis kill), l'entree quitte
    la file et ``pipeline.json`` passe ``failed``. Le vrai worker, en voyant son enfant termine, garde cette
    raison (ecrite apres le lancement). Rien d'autre n'est touche : ni les publications, ni les reprises."""
    config = config or load_config()
    path = _queue_path(config)
    with _locked(path):
        entry = next((e for e in _read_queue(path) if e["video_id"] == video_id and e["status"] == "running"), None)
    if entry is None:
        _cancel_interrupted(video_id, config)
        return

    _terminate_pid(entry["pid"], float(config.section("worker")["cancel_grace_s"]))
    with _locked(path):
        _write_queue(path, [e for e in _read_queue(path) if e["id"] != entry["id"]])

    from clipper import pipeline

    try:
        state = pipeline.load_state(video_id, config=config)
    except pipeline.PipelineError:
        state = pipeline.new_state(video_id, entry["url"], config.mode, channel=entry.get("channel"))
    state.pop("dismissed_at", None)
    state.update(status="failed", reason=_CANCEL_REASON, retry_at=None)
    pipeline.save_state(state, config=config)


def _cancel_interrupted(video_id: str, config: Config) -> None:
    """Annuler une vidéo interrompue (``running`` sans processus) : l'étape orpheline repasse ``pending``, la vidéo
    ``failed`` « annulée », journalisé ; les étapes terminées sont conservées."""
    from clipper import pipeline

    try:
        state = pipeline.load_state(video_id, config=config)
    except pipeline.PipelineError:
        state = None
    if state is None or not is_interrupted(state, config):
        raise WorkerError(f"aucune video en cours pour {video_id!r}")
    mark_interrupted(video_id, config, cancelled=True)


def _terminate_pid(pid: int | None, grace: float) -> None:
    """Arrete le processus ``pid`` s'il vit encore : demande d'arret, ``grace`` secondes, puis kill."""
    if not _pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)  # Windows : TerminateProcess
    except OSError as exc:
        if _pid_alive(pid):
            raise WorkerError(f"processus {pid} impossible à arrêter : {exc}") from exc
        return
    deadline = time.monotonic() + grace
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _pid_alive(pid):
        try:
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError as exc:
            log.error("processus %s : kill impossible après %g s : %s", pid, grace, exc)


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
    if "short_clips" in entry:  # absent : valeur du style (anciennes entrees)
        cmd.append("--short-clips" if entry["short_clips"] else "--no-short-clips")
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
        youtube_publisher: Callable[..., dict[str, Any]] | None = None,
        veille_collectors: dict[str, Callable[..., dict[str, Any]]] | None = None,
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
        self.veille_collectors = veille_collectors  # None : les collecteurs reels de clipper.veille_sources
        self._logged_veille_errors: set[str] = set()
        self.publisher = publisher or tiktok.publish
        self.youtube_publisher = youtube_publisher or youtube.publish  # compte YouTube (SPEC-5e50 R2)
        self._logged_publish_errors: set[str] = set()
        self.stats_fetcher = stats_fetcher or tiktok.fetch_stats
        self.login_checker = login_checker or browser.login_state  # connexion verifiee avant chaque publication
        self._stats_attempts: dict[str, datetime] = {}
        self._logged_stats_errors: set[str] = set()
        self._path = _queue_path(self.config)
        self._process: Any | None = None
        self._entry: dict[str, Any] | None = None
        self._last_beat: float | None = None

    def startup(self) -> None:
        """Reprises de demarrage du vrai worker (``clipper worker``, appelees par ``loop`` seulement) : orphelins
        de la file, publications interrompues, migration des anciens styles. Jamais dans le constructeur : un
        autre processus qui construirait un Worker passerait en echec la publication que le worker pilote."""
        self._recover_orphans()
        self._recover_interrupted_videos()
        self._recover_interrupted_publications()
        self._migrate_legacy_presets()

    def _migrate_legacy_presets(self) -> None:
        """Au demarrage : creneaux et compte d'un ancien style repris sur le compte (SPEC-6076 R2), journalise."""
        try:
            watch = self.config.section("watch")
            channel_mod.migrate_legacy_presets(self.config, presets_dir=watch["presets_dir"], base=watch["base_config"])
        except (channel_mod.ChannelError, ConfigError, OSError, ValueError) as exc:
            log.error("migration des anciens styles impossible : %s", exc)

    def _recover_interrupted_videos(self) -> None:
        """Au démarrage, une étape restée ``running`` sans entrée vivante dans la file (serveur ou PC arrêté
        pendant le traitement) est marquée interrompue et journalisée (TASK-bdd5) : jamais laissée « en cours »."""
        from clipper import pipeline

        root = Path(self.config.workspace_dir)
        for path in sorted(root.glob(f"*/{pipeline.STATE_FILE}")) if root.is_dir() else []:
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if state.get("status") == "running" and not _live_in_queue(state["video_id"], self.config):
                    mark_interrupted(state["video_id"], self.config)
            except (OSError, ValueError, KeyError, pipeline.PipelineError) as exc:
                log.error("reprise des vidéos interrompues : %s illisible : %s", path, exc)

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

    def _beat(self, *, busy: bool = False, force: bool = False) -> None:
        """Écrit ``{pid, at, busy}`` dans ``heartbeat_path`` si ``heartbeat_interval_s``
        s'est écoulé depuis le dernier battement (écriture atomique). ``busy`` : le worker reprend lui-même des
        vidéos en file (pas d'entrée ``running`` pour elles) ; ``force`` écrit sans attendre l'intervalle."""
        section = self.config.section("worker")
        now = time.monotonic()
        if not force and self._last_beat is not None and now - self._last_beat < float(section["heartbeat_interval_s"]):
            return
        path = heartbeat_path(self.config)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "at": datetime.now(timezone.utc).isoformat(), "busy": busy}),
                       encoding="utf-8")
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
        self._veille_due()
        if not self._publish_due():
            self._stats_due()

        if self._process is not None:
            if self._process.poll() is None:
                return
            self._finish_current()
            self._veille_select_best()

        if self._launch_head():
            return

        from clipper import pipeline

        busy = bool(pipeline.queued(config=self.config))
        if busy:
            self._beat(busy=True, force=True)  # les reprises tournent dans ce processus : pas « interrompues »
        try:
            pipeline.process_queue(config=self.config)
        except Exception:  # noqa: BLE001 - jamais un worker mort (Mineur 1, revue r-transcription) :
            # la file reste reprise au tick suivant, l'exception est seulement journalisee.
            log.exception("reprise de la file de pipeline interrompue par une erreur inattendue")
        finally:
            if busy:
                self._beat(force=True)

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

    def _log_veille_error(self, exc: Exception) -> None:
        message = str(exc)
        if message not in self._logged_veille_errors:
            self._logged_veille_errors.add(message)
            log.error("veille impossible : %s", message)

    def _veille_due(self) -> None:
        """Releve quotidien ou « Rafraichir » de la veille (SPEC-bdd9 R7), dans ce processus seulement.
        Une erreur de reglage ou d'etat est journalisee une fois et n'arrete pas le worker."""
        from clipper import veille

        try:
            veille.run_if_due(datetime.now(timezone.utc), self.config, self.veille_collectors)
        except (veille.VeilleError, ConfigError) as exc:
            self._log_veille_error(exc)

    def _veille_select_best(self) -> None:
        """Apres chaque fin de processus enfant : recalcule les meilleurs clips du jour (SPEC-bdd9 R7)."""
        from clipper import veille

        try:
            veille.select_best(datetime.now(timezone.utc), self.config)
        except (veille.VeilleError, ConfigError) as exc:
            self._log_veille_error(exc)

    # ------------------------------------------------------------ publication TikTok

    def _publish_due(self) -> bool:
        """Une publication TikTok due par iteration (SPEC-9225 R3) ; vrai si une tentative a eu lieu.
        Une file, un preset ou un reglage illisible est journalise une fois (ADR-ad2e) et ne tue
        pas le worker. ``OSError``/``ValueError`` (dont ``JSONDecodeError``) couvrent un fichier de
        publication tronque ou un ``slot_at`` mal forme (M2, revue r-fable-publication) : sans eux,
        l'exception traversait jusqu'a ``tick``/``loop`` et tuait le worker."""
        try:
            return self._publish_next()
        except (publish_mod.PublishError, channel_mod.ChannelError, ConfigError, tiktok.TikTokError,
                youtube.YouTubeError, accounts_mod.AccountsError, OSError, ValueError) as exc:
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
                if not found["ready_to_publish"] or found.get("service") == "youtube":
                    continue  # les statistiques YouTube viennent d'une autre tache : jamais releves par la page TikTok
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

    def _service_settings(self, service: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Reglages [tiktok] ou [youtube] du service d'un compte, lus (et valides) une fois par passage."""
        if service not in cache:
            cache[service] = youtube.get_settings(self.config) if service == "youtube" else tiktok.get_settings(self.config)
        return cache[service]

    def _publish_next(self) -> bool:
        now = datetime.now(timezone.utc)
        services = {a["id"]: a.get("service") or "tiktok" for a in accounts_mod.list_accounts(self.config)}
        cache: dict[str, dict[str, Any]] = {}
        watch = self.config.section("watch")
        paths = {"state_dir": self.config.section("publish")["state_dir"],
                 "presets_dir": watch["presets_dir"], "base": watch["base_config"]}
        due = []
        # la file des videos sans chaine (SPEC-1ed3 R3) est lue comme celle d'une chaine sans creneau ni compte
        for name in [*channel_mod.list_channels(paths["presets_dir"]), publish_mod.NO_CHANNEL]:
            for entry in publish_mod.list_entries(name, state_dir=paths["state_dir"]):
                if entry["status"] != "scheduled" or not entry["slot_at"]:
                    continue
                slot = datetime.fromisoformat(entry["slot_at"])
                account = publish_mod.entry_account(entry)
                service = services.get(account, "tiktok")  # compte inconnu : _publish_one l'explique (R4)
                settings = self._service_settings(service, cache)
                mode = entry.get("publish_mode") or str(settings["publish_mode"])
                window = timedelta(days=float(settings["schedule_max_days"])) if mode == "scheduled" else timedelta(0)
                if slot - window <= now:  # immediat : creneau atteint ; programme : date dans la fenetre TikTok
                    due.append((slot, name, entry, mode, service, settings))
        due.sort(key=lambda d: (d[0], d[1], d[2]["clip_id"]))
        for slot, name, entry, mode, service, settings in due:
            if self._publish_one(slot, name, entry, mode, settings, paths, now, service):
                return True
        return False

    def _publish_one(self, slot: datetime, name: str, entry: dict[str, Any], mode: str,
                     settings: dict[str, Any], paths: dict[str, Any], now: datetime, service: str = "tiktok") -> bool:
        """Vrai si la tentative de publication a eu lieu (reussie ou en echec) : fin de l'iteration. ``service`` et
        ``settings`` : ceux du compte de l'entree (SPEC-5e50 : plafonds et module de publication par service)."""
        video_id, clip_id = entry["video_id"], entry["clip_id"]
        label = publish_mod.SERVICE_LABELS[service]
        account = publish_mod.entry_account(entry)  # jamais un autre compte en repli (SPEC-6076 R2)
        where = {"channel": name, "video_id": video_id, "clip_id": clip_id}
        if not account:
            self._fail(entry, name,
                       "aucun compte de publication choisi : modifie la publication et choisis un compte prêt à publier",
                       halted=False, account=None, state_dir=paths["state_dir"])
            return False
        target = slot if mode == "scheduled" else now
        waiting_for = self._previous_part_missing(entry, name, target, paths["state_dir"])
        if waiting_for is not None:
            self._wait(entry, name, account, waiting_for, paths["state_dir"])
            return False
        if not self._account_ready(entry, name, account, paths["state_dir"]):
            return False
        account_row = next(a for a in accounts_mod.list_accounts(self.config) if a["id"] == account)
        schedule = accounts_mod.schedule_of(account_row)
        scope = {"state_dir": paths["state_dir"], "presets_dir": paths["presets_dir"], "base": paths["base"]}
        halt = publish_mod.halted_account(account, **scope)
        if halt is not None:
            # arret sur en cours (R4) : rien ne part avant « Reessayer » (ou l'annulation) de l'entree
            # en echec qui a arrete le compte ; la raison reste visible plutot qu'un blocage silencieux
            # (I1, revue r-fable-publication).
            self._wait(entry, name, account,
                       f"compte arrêté par l'échec de {halt['video_id']}/{halt['clip_id']} "
                       f"({halt['error']}) : réessaie-la ou annule-la", paths["state_dir"])
            return False

        times = publish_mod.account_publish_times(account, **scope)
        # Plafonds par compte (SPEC-6076 R6) : le fuseau est celui du COMPTE, pas du style (revue r-comptes 9).
        tz = ZoneInfo(str(schedule["timezone"]))
        blocked = tiktok.check_limits(times, slot if mode == "scheduled" else now, settings, tz)
        if blocked is not None and entry.get("manual"):
            # publication pilotee depuis l'ecran Publication : le plafond a deja ete verifie au formulaire ; s'il
            # est depasse depuis, l'entree attend avec la raison, jamais reportee ni deplacee (SPEC-1ed3 R4)
            self._wait(entry, name, account, f"{blocked} : la publication attend, modifie son heure ou annule-la",
                       paths["state_dir"])
            return False
        if blocked is not None:
            if not schedule["slots"]:  # rien a reporter sans creneau sur le compte (SPEC-6076 R2)
                self._wait(entry, name, account, f"{blocked} : le compte n'a aucun créneau pour reporter la publication "
                           "(Comptes > Créneaux), modifie son heure ou annule-la", paths["state_dir"])
                return False
            moved = publish_mod.postpone(
                video_id, clip_id, name, blocked, now=now, schedule=schedule,
                allowed=lambda candidate: tiktok.check_limits(times, candidate, settings, tz), **scope)
            log.warning("%s/%s : %s", video_id, clip_id, moved["postponed_reason"])
            tiktok.emit_event({"level": "warn", "account": account, **where, "reason": moved["postponed_reason"],
                               "capture": None}, config=self.config)
            return False

        if service == "tiktok" and not self._connected(entry, name, account, paths["state_dir"]):
            return False  # YouTube : la connexion est « prete a publier » (derniere verification) ; Studio arrete sur Google
        try:
            network.require_expected_country(self.config)
        except network.NetworkUnknown as exc:
            # service de geolocalisation injoignable : condition transitoire, l'entree attend et sera retentee ;
            # le compte reste « pret a publier » et le navigateur n'est pas ouvert (I2, revue nuit)
            self._wait(entry, name, account, str(exc), paths["state_dir"])
            return False
        except network.NetworkError as exc:  # IP dans un autre pays : arret sur (R4)
            self._fail(entry, name, str(exc), halted=True, account=account, state_dir=paths["state_dir"])
            return True
        if entry.get("waiting_reason"):
            publish_mod.set_waiting_reason(video_id, clip_id, name, None, state_dir=paths["state_dir"])
        try:
            # prise en main atomique : l'entree a pu changer (compte, date, reglages, refus) pendant la verification
            # de connexion ; sinon elle n'est pas pilotee et sera relue au prochain passage
            publish_mod.mark_in_progress(video_id, clip_id, name, expected=entry, state_dir=paths["state_dir"])
        except publish_mod.PublishError as exc:
            log.warning("%s/%s : non pilotée : %s", video_id, clip_id, exc)
            return False
        try:
            payload = youtube.clip_payload if service == "youtube" else tiktok.clip_payload
            clip = payload(publish_mod.read_sidecar(self.config.output_dir, video_id, clip_id), self.config.output_dir)
            extra = {"options": entry["post_options"]} if entry.get("post_options") else {}
            publisher = self.youtube_publisher if service == "youtube" else self.publisher
            result = publisher(clip, account, mode=mode, schedule_at=slot if mode == "scheduled" else None,
                               config=self.config, on_tick=self._beat, **extra)
        except tiktok.TikTokStop as stop:
            if stop.code == "content_check_refused":
                self._refused(entry, name, stop.reason, account=account, capture=stop.capture,
                              state_dir=paths["state_dir"])
            else:
                self._fail(entry, name, stop.reason, halted=True, account=account, capture=stop.capture,
                           state_dir=paths["state_dir"])
        except youtube.YouTubeStop as stop:
            self._fail(entry, name, stop.reason, halted=True, account=account, capture=stop.capture,
                       state_dir=paths["state_dir"])
        except browser.BrowserUnavailable as exc:  # pays devenu inconnu pendant la prise en main : echec reessayable
            self._fail(entry, name, str(exc), halted=False, account=account, state_dir=paths["state_dir"])
        except browser.BrowserError as exc:
            self._fail(entry, name, str(exc), halted=True, account=account, state_dir=paths["state_dir"])
        except (tiktok.TikTokError, youtube.YouTubeError, publish_mod.PublishError) as exc:
            self._fail(entry, name, str(exc), halted=False, account=account, state_dir=paths["state_dir"])
        except Exception as exc:  # noqa: BLE001 - jamais un worker mort : l'entree echoue, avec la raison
            log.exception("%s/%s : erreur inattendue pendant la publication", video_id, clip_id)
            self._fail(entry, name, f"erreur inattendue : {type(exc).__name__} : {exc}", halted=True,
                       account=account, state_dir=paths["state_dir"])
        else:
            publish_mod.mark_published(
                video_id, clip_id, name, state_dir=paths["state_dir"], output_dir=self.config.output_dir,
                tiktok_state=result["state"], post_url=result["post_url"], post_id=result["post_id"],
                publish_at=result["publish_at"], post_note=result["note"], account=account, service=service)
            done = f"programmée sur {label}" if result["state"].startswith("scheduled_on_") else "publiée"
            log.info("%s/%s : %s (%s)", video_id, clip_id, done, result["post_url"] or result["note"])
            tiktok.emit_event({"level": "info", "account": account, **where,
                               "reason": f"{done} : {result['post_url'] or result['note']}", "capture": None},
                              config=self.config)
        return True

    @staticmethod
    def _previous_part_missing(entry: dict[str, Any], channel: str, target: datetime,
                               state_dir: str | Path) -> str | None:
        """Une serie part entiere et dans l'ordre : la partie N>1 attend que la partie N-1 soit publiee, ou
        programmee sur le service a une date qui ne passe pas apres ``target`` (date visee de la partie N).
        Rend la raison de l'attente, None si la partie peut partir. ``parts_together`` explicitement False
        (coche « Parties ensemble » decochee, TASK-fc561e4dc7e9) leve cette attente : la partie est
        independante de ses soeurs."""
        series_id, part = entry.get("series_id"), entry.get("part")
        if not series_id or not isinstance(part, int) or part <= 1:
            return None
        if entry.get("parts_together") is False:
            return None
        siblings = [e for e in publish_mod.list_entries(channel, state_dir=state_dir)
                    if e["video_id"] == entry["video_id"] and e.get("series_id") == series_id]
        number = part - 1
        # une partie refusee par TikTok (verification de contenu) sort de la serie : la serie continue sans elle
        while number >= 1:
            found = next((e for e in siblings if e.get("part") == number), None)
            if found is None or found["status"] != publish_mod.REFUSED_BY_PLATFORM:
                break
            log.info("%s/%s : partie %d refusée par TikTok, série poursuivie", entry["video_id"], found["clip_id"], number)
            number -= 1
        if number < 1:
            return None
        previous = next((e for e in siblings if e.get("part") == number), None)
        reason = f"partie {number} non publiée"
        if previous is None:
            return f"{reason} (absente de la file) : la série part entière et dans l'ordre"
        if previous["status"] != "published":
            return f"{reason} (statut {previous['status']}) : la série part entière et dans l'ordre"
        if str(previous.get("tiktok_state") or "").startswith("scheduled_on_"):
            at = previous.get("tiktok_publish_at")
            if not at or datetime.fromisoformat(at) > target:
                return f"{reason} : programmée sur le service le {at or 'date inconnue'}, après cette partie"
        return None

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

    def _refused(self, entry: dict[str, Any], channel: str, reason: str, *, account: str | None,
                 state_dir: str | Path, capture: Path | None = None) -> None:
        """Probleme signale par TikTok a la verification de contenu (TASK-7f582251f6c5) : rien n'est publie, l'entree
        passe en ``refused_by_platform`` (raison + capture), journal et evenement console ; contrairement a ``_fail``,
        le compte n'est PAS arrete (« pret a publier » reste coche) et la publication suivante part normalement."""
        video_id, clip_id = entry["video_id"], entry["clip_id"]
        log.error("%s/%s : refusé par TikTok : %s", video_id, clip_id, reason)
        publish_mod.mark_refused_by_platform(video_id, clip_id, channel, reason, capture=capture, state_dir=state_dir)
        tiktok.emit_event({"level": "error", "account": account, "channel": channel, "video_id": video_id,
                           "clip_id": clip_id, "reason": f"refusé par TikTok : {reason}",
                           "capture": str(capture) if capture else None}, config=self.config)

    def _fail(self, entry: dict[str, Any], channel: str, reason: str, *, halted: bool, account: str | None,
              state_dir: str | Path, capture: Path | None = None) -> None:
        """Entree ``failed`` (reessayable), journal et evenement console (SPEC-9225 R4). Un arret R4 decoche
        aussi « pret a publier » du compte, jusqu'a ce que l'utilisateur le recoche (SPEC-00d1 R3)."""
        video_id, clip_id = entry["video_id"], entry["clip_id"]
        log.error("%s/%s : publication en échec : %s", video_id, clip_id, reason)
        publish_mod.mark_failed(video_id, clip_id, channel, reason, capture=capture, halted=halted, state_dir=state_dir)
        if halted and account:
            try:
                accounts_mod.uncheck_ready(self.config, account, f"arrêt de publication : {reason}")
            except accounts_mod.AccountsError as exc:
                log.error("compte %s : « prêt à publier » non décoché : %s", account, exc)
        tiktok.emit_event({"level": "error", "account": account, "channel": channel, "video_id": video_id,
                           "clip_id": clip_id, "reason": reason, "capture": str(capture) if capture else None},
                          config=self.config)

    def _sync_channel_mode(self, name: str) -> None:
        """L'enfant lance par ``--config presets/<chaine>.toml`` lit le mode
        de TETE du preset (``__main__.load_config``), jamais ``[channel].mode``
        directement : les deux sont donc tenus synchronises avant chaque
        lancement, sinon l'enfant tourne dans le mode global au lieu de celui
        de la chaine (Important 1, revue r-transcription). ``[channel].mode``
        explicite est copie en tete ; vide (herite du mode global), toute
        tete laissee par une synchronisation precedente est retiree, sinon la
        chaine resterait figee sur cet ancien mode au lieu de suivre le mode
        global courant (la tete, si elle restait, masquerait tout changement
        de ``config.toml``). Un preset ou un reglage illisible est journalise
        une fois et ne bloque jamais le lancement (ADR-ad2e : visible,
        jamais silencieux ni fatal)."""
        watch = self.config.section("watch")
        presets_dir, base = watch["presets_dir"], watch["base_config"]
        path = Path(presets_dir) / f"{name}.toml"
        try:
            with path.open("rb") as f:
                raw = tomllib.load(f)
            channel_mod.load_channel(name, presets_dir=presets_dir, base=base)  # valide le preset
        except (channel_mod.ChannelError, ConfigError, OSError, tomllib.TOMLDecodeError) as exc:
            log.error("%s : synchronisation du mode de chaîne impossible : %s", name, exc)
            return
        explicit = str((raw.get("channel") or {}).get("mode") or "")
        if explicit:
            if raw.get("mode") == explicit:
                return
            data = {**raw, "mode": explicit}
        elif "mode" in raw:
            data = {k: v for k, v in raw.items() if k != "mode"}
        else:
            return
        try:
            channel_mod.save_channel(name, data, presets_dir=presets_dir, base=base)
        except (channel_mod.ChannelError, ConfigError, OSError) as exc:
            log.error("%s : synchronisation du mode de chaîne impossible : %s", name, exc)

    def _launch_head(self) -> bool:
        """Lance la tete de file ``waiting`` ; le cycle relecture-lancement-
        ecriture est sous verrou, la file ayant pu changer (API web) depuis
        le dernier tick. Faux si rien n'attend."""
        with _locked(self._path):
            entries = _read_queue(self._path)
            entry = next((e for e in entries if e["status"] == "waiting"), None)
            if entry is None:
                return False
            if entry.get("channel"):
                self._sync_channel_mode(entry["channel"])
            self._launched_at = datetime.now(timezone.utc)
            self._keep_channel(entry)
            process = self._spawn(entry, _build_command(entry))
            entry["status"] = "running"
            entry["pid"] = process.pid
            _write_queue(self._path, entries)
        self._process = process
        self._entry = entry
        return True

    def _keep_channel(self, entry: dict[str, Any]) -> None:
        """Ecrit le style de l'entree dans ``pipeline.json`` avant le lancement (TASK-9d24) : l'enfant
        (``clipper run|render``) ne le connait que par ``--config`` et ne l'ecrit pas, et une relance
        (``_channel_of``, ``enqueue_resume``) le relit depuis l'etat. Un style deja attribue est conserve ;
        une entree sans style n'en invente pas."""
        from clipper import pipeline

        channel = entry.get("channel")
        if not channel:
            return
        try:
            state = pipeline.load_state(entry["video_id"], config=self.config)
        except pipeline.PipelineError:
            state = pipeline.new_state(entry["video_id"], entry["url"], self.config.mode, channel=channel)
        else:
            if state.get("channel"):
                return
            state["channel"] = channel
        pipeline.save_state(state, config=self.config)

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

    def loop(self) -> None:
        """Boucle jusqu'a interruption, a l'intervalle ``poll_interval_s``
        de CONFIG_DEFAULTS (SPEC-74e9 §2.3)."""
        interval = float(self.config.section("worker")["poll_interval_s"])
        self.startup()
        while True:
            self.tick()
            time.sleep(interval)
