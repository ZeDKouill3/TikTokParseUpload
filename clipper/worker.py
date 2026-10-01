"""Worker separe du serveur HTTP (ADR-4f6e §1) : boucle sur la file
``state/queue.json`` (SPEC-fc0c §2) et lance chaque video dans un processus
enfant ``python -m clipper <action> <url|id>``, un seul a la fois
(ADR-fb9b). N'importe que clipper.pipeline, clipper.channel et
clipper.config : jamais clipper.web, jamais une etape (ADR-b16b).

Entree de file (SPEC-fc0c §2.1) : {id, video_id, url, channel | null,
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from clipper import channel as channel_mod
from clipper.config import Config, ConfigError, load_config

log = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    "poll_interval_s": 2,
    "cancel_grace_s": 10,
    "queue_path": "state/queue.json",
}

_CANCEL_REASON = "annulée par l'utilisateur"


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
    deux processus, ADR-4f6e)."""
    return channel_mod.file_lock(path)


def enqueue(
    url: str,
    channel: str | None,
    action: str,
    force_steps: list[str] | None = None,
    *,
    config: Config | None = None,
) -> dict[str, Any]:
    """Ajoute une entree a la file (SPEC-fc0c §2.1), ecriture atomique.
    ``url`` est l'URL source pour ``action="run"``, le video_id pour
    ``action="render"`` (deja lance, pas d'URL a resoudre). Refuse un
    doublon deja ``waiting`` pour le meme video_id et la meme action
    (SPEC-fc0c §2.2)."""
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
    attente, sans toucher l'entree ``running`` (SPEC-fc0c §2.2)."""
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
    ``running`` (SPEC-fc0c §2.2)."""
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
    cmd = [sys.executable, "-m", "clipper", entry["action"], entry["url"] if entry["action"] == "run" else entry["video_id"]]
    if entry.get("channel"):
        cmd += ["--config", f"presets/{entry['channel']}.toml"]
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
    ) -> None:
        if spawner is None:
            import subprocess

            spawner = subprocess.Popen
        self.config = config or load_config()
        self.spawner = spawner
        self.watch_lister = watch_lister
        self._logged_watch_errors: set[str] = set()
        self._path = _queue_path(self.config)
        self._process: Any | None = None
        self._entry: dict[str, Any] | None = None
        self._recover_orphans()

    def _recover_orphans(self) -> None:
        """Au demarrage, une entree ``running`` dont le pid est mort
        (worker precedent tombe) repasse ``waiting`` en tete (SPEC-fc0c
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
        les videos ``queued`` dont ``retry_at`` est passe (SPEC-fc0c
        §2.3-2.4). La surveillance des chaines echues passe d'abord, enfant
        en cours ou non (SPEC-fc0c §5.1)."""
        self._watch_channels()

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

    def _launch_head(self) -> bool:
        """Lance la tete de file ``waiting`` ; le cycle relecture-lancement-
        ecriture est sous verrou, la file ayant pu changer (API web) depuis
        le dernier tick. Faux si rien n'attend."""
        with _locked(self._path):
            entries = _read_queue(self._path)
            entry = next((e for e in entries if e["status"] == "waiting"), None)
            if entry is None:
                return False
            process = self.spawner(_build_command(entry))
            entry["status"] = "running"
            entry["pid"] = process.pid
            _write_queue(self._path, entries)
        self._process = process
        self._entry = entry
        return True

    def _finish_current(self) -> None:
        video_id = self._entry["video_id"]
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
        ``pipeline.json`` en ``failed`` (SPEC-fc0c §2.3)."""
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
        de CONFIG_DEFAULTS (SPEC-fc0c §2.3)."""
        interval = float(self.config.section("worker")["poll_interval_s"])
        while True:
            self.tick()
            time.sleep(interval)
