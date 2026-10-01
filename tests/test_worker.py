"""worker.py : file state/queue.json, processus enfant par video (TASK-bbe4).

Le vrai pipeline n'est jamais lance : ``tick()`` recoit un spawner injecte
(faux processus, ou un vrai script python trivial pour les tests de
terminaison / orphelin) au lieu de subprocess.Popen. Aucun reseau.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from clipper import pipeline, worker
from clipper.config import Config

VIDEO_A = "AAAAAAAAAAA"
VIDEO_B = "BBBBBBBBBBB"
URL_A = f"https://youtu.be/{VIDEO_A}"
URL_B = f"https://youtu.be/{VIDEO_B}"


def _config(tmp_path, **worker_overrides) -> Config:
    return Config(
        mode="auto",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={"worker": {"queue_path": str(tmp_path / "state" / "queue.json"), **worker_overrides}},
    )


def _queue(config: Config) -> list[dict]:
    path = worker._queue_path(config)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_queue(config: Config, entries: list[dict]) -> None:
    path = worker._queue_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


class FakeProcess:
    """Substitut de subprocess.Popen injecte comme spawner : pid fixe,
    poll() controle par le test, terminate()/kill() comptes."""

    def __init__(self, pid: int = 4242, alive_after_terminate: bool = False):
        self.pid = pid
        self._returncode = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self._alive_after_terminate = alive_after_terminate

    def poll(self):
        return self._returncode

    def finish(self, code: int = 0) -> None:
        self._returncode = code

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self._alive_after_terminate:
            self._returncode = -15

    def kill(self) -> None:
        self.kill_calls += 1
        self._returncode = -9


class FakeSpawner:
    def __init__(self, process: FakeProcess | None = None):
        self.calls: list[list[str]] = []
        self.process = process or FakeProcess()

    def __call__(self, cmd: list[str]):
        self.calls.append(cmd)
        return self.process


def _pipeline_state(video_id: str, config: Config, *, status: str = "running") -> dict:
    state = pipeline.new_state(video_id, f"https://youtu.be/{video_id}", config.mode)
    state["status"] = status
    pipeline.save_state(state, config=config)
    return state


# --------------------------------------------------------------------------
# (1) enqueue
# --------------------------------------------------------------------------


def test_enqueue_writes_entry_to_queue_json(tmp_path):
    config = _config(tmp_path)

    entry = worker.enqueue(URL_A, "ma_chaine", "run", ["render"], config=config)

    entries = _queue(config)
    assert entries == [entry]
    assert entry["video_id"] == VIDEO_A
    assert entry["url"] == URL_A
    assert entry["channel"] == "ma_chaine"
    assert entry["action"] == "run"
    assert entry["force_steps"] == ["render"]
    assert entry["status"] == "waiting"
    assert entry["pid"] is None
    assert entry["enqueued_at"]
    assert entry["id"]


def test_enqueue_refuses_duplicate_waiting_same_video_and_action(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)

    with pytest.raises(worker.WorkerError):
        worker.enqueue(URL_A, None, "run", config=config)

    assert len(_queue(config)) == 1


def test_enqueue_allows_same_video_different_action(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)

    worker.enqueue(URL_A, None, "render", config=config)

    assert len(_queue(config)) == 2


def test_enqueue_allows_duplicate_when_existing_entry_is_running(tmp_path):
    config = _config(tmp_path)
    entries = [{
        "id": "x", "video_id": VIDEO_A, "url": URL_A, "channel": None, "action": "run",
        "force_steps": [], "enqueued_at": "2026-01-01T00:00:00+00:00", "status": "running", "pid": 1,
    }]
    _write_queue(config, entries)

    worker.enqueue(URL_A, None, "run", config=config)

    assert len(_queue(config)) == 2


# --------------------------------------------------------------------------
# (1) move_to_front / remove
# --------------------------------------------------------------------------


def _entry(video_id: str, url: str, status: str = "waiting", pid=None) -> dict:
    return {
        "id": video_id, "video_id": video_id, "url": url, "channel": None, "action": "run",
        "force_steps": [], "enqueued_at": "2026-01-01T00:00:00+00:00", "status": status, "pid": pid,
    }


def test_move_to_front_reorders_waiting_without_touching_running(tmp_path):
    config = _config(tmp_path)
    running = _entry(VIDEO_A, URL_A, status="running", pid=99)
    b, c, d = _entry("B", "https://youtu.be/B"), _entry("C", "https://youtu.be/C"), _entry("D", "https://youtu.be/D")
    _write_queue(config, [running, b, c, d])

    worker.move_to_front("D", config=config)

    entries = _queue(config)
    assert entries[0]["video_id"] == VIDEO_A
    assert entries[0]["status"] == "running"
    assert [e["video_id"] for e in entries[1:]] == ["D", "B", "C"]


def test_move_to_front_raises_for_unknown_video(tmp_path):
    config = _config(tmp_path)
    _write_queue(config, [_entry("B", "https://youtu.be/B")])

    with pytest.raises(worker.WorkerError):
        worker.move_to_front("nope", config=config)


def test_remove_removes_waiting_without_touching_running(tmp_path):
    config = _config(tmp_path)
    running = _entry(VIDEO_A, URL_A, status="running", pid=99)
    b = _entry("B", "https://youtu.be/B")
    _write_queue(config, [running, b])

    worker.remove("B", config=config)

    entries = _queue(config)
    assert [e["video_id"] for e in entries] == [VIDEO_A]
    assert entries[0]["status"] == "running"


def test_remove_raises_when_nothing_waiting_matches(tmp_path):
    config = _config(tmp_path)
    _write_queue(config, [_entry(VIDEO_A, URL_A, status="running", pid=99)])

    with pytest.raises(worker.WorkerError):
        worker.remove(VIDEO_A, config=config)


# --------------------------------------------------------------------------
# (2) tick : lance la tete de file via le spawner
# --------------------------------------------------------------------------


def test_tick_launches_head_entry_with_exact_command_line_run_action(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, "ma_chaine", "run", ["parts", "render"], config=config)
    spawner = FakeSpawner()

    w = worker.Worker(config=config, spawner=spawner)
    w.tick()

    assert spawner.calls == [[
        sys.executable, "-m", "clipper", "run", URL_A,
        "--config", "presets/ma_chaine.toml",
        "--force-step", "parts", "--force-step", "render",
    ]]


def test_tick_launches_head_entry_with_exact_command_line_render_action(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(VIDEO_A, None, "render", config=config)
    spawner = FakeSpawner()

    w = worker.Worker(config=config, spawner=spawner)
    w.tick()

    assert spawner.calls == [[sys.executable, "-m", "clipper", "render", VIDEO_A]]


def test_tick_records_pid_and_marks_entry_running(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)
    spawner = FakeSpawner(FakeProcess(pid=1234))

    worker.Worker(config=config, spawner=spawner).tick()

    entries = _queue(config)
    assert entries[0]["status"] == "running"
    assert entries[0]["pid"] == 1234


def test_tick_launches_nothing_else_while_child_alive(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)
    worker.enqueue(URL_B, None, "run", config=config)
    spawner = FakeSpawner()

    w = worker.Worker(config=config, spawner=spawner)
    w.tick()
    w.tick()
    w.tick()

    assert len(spawner.calls) == 1
    entries = _queue(config)
    assert [e["status"] for e in entries] == ["running", "waiting"]


def test_tick_removes_entry_and_starts_next_once_child_finishes(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)
    worker.enqueue(URL_B, None, "run", config=config)
    process_a = FakeProcess()
    spawner = FakeSpawner(process_a)

    w = worker.Worker(config=config, spawner=spawner)
    w.tick()
    process_a.finish(0)
    w.tick()

    entries = _queue(config)
    assert [e["video_id"] for e in entries] == [VIDEO_B]
    assert len(spawner.calls) == 2


# --------------------------------------------------------------------------
# (5) tick : reprend la file du pipeline (retry_at passe)
# --------------------------------------------------------------------------


def test_tick_calls_pipeline_process_queue_when_nothing_to_launch(tmp_path, monkeypatch):
    config = _config(tmp_path)
    calls = []
    monkeypatch.setattr(pipeline, "process_queue", lambda *, config: calls.append(config))

    worker.Worker(config=config, spawner=FakeSpawner()).tick()

    assert calls == [config]


# --------------------------------------------------------------------------
# (3) cancel
# --------------------------------------------------------------------------


def test_cancel_terminates_child_and_marks_pipeline_failed(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)
    process = FakeProcess()
    spawner = FakeSpawner(process)
    _pipeline_state(VIDEO_A, config, status="running")

    w = worker.Worker(config=config, spawner=spawner)
    w.tick()
    w.cancel(VIDEO_A)

    assert process.terminate_calls == 1
    assert _queue(config) == []
    state = pipeline.load_state(VIDEO_A, config=config)
    assert state["status"] == "failed"
    assert state["reason"] == "annulée par l'utilisateur"


def test_cancel_kills_after_grace_if_still_alive(tmp_path):
    config = _config(tmp_path, cancel_grace_s=0)
    worker.enqueue(URL_A, None, "run", config=config)
    process = FakeProcess(alive_after_terminate=True)
    spawner = FakeSpawner(process)
    _pipeline_state(VIDEO_A, config, status="running")

    w = worker.Worker(config=config, spawner=spawner)
    w.tick()
    w.cancel(VIDEO_A)

    assert process.terminate_calls == 1
    assert process.kill_calls == 1


def test_cancel_raises_when_video_not_running(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)

    with pytest.raises(worker.WorkerError):
        worker.Worker(config=config, spawner=FakeSpawner()).cancel(VIDEO_A)


# --------------------------------------------------------------------------
# (4) demarrage : orphelin (pid mort) repasse waiting en tete
# --------------------------------------------------------------------------


def test_worker_startup_recovers_dead_orphan_to_waiting_front(tmp_path):
    import subprocess

    config = _config(tmp_path)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    dead_pid = dead.pid

    orphan = _entry(VIDEO_A, URL_A, status="running", pid=dead_pid)
    other = _entry("B", "https://youtu.be/B", status="waiting")
    _write_queue(config, [other, orphan])

    worker.Worker(config=config, spawner=FakeSpawner())

    entries = _queue(config)
    assert entries[0]["video_id"] == VIDEO_A
    assert entries[0]["status"] == "waiting"
    assert entries[0]["pid"] is None
    assert entries[1]["video_id"] == "B"


# --------------------------------------------------------------------------
# (6) python -m clipper worker / serve
# --------------------------------------------------------------------------


def test_loop_ticks_and_sleeps_at_configured_interval(tmp_path, monkeypatch):
    config = _config(tmp_path, poll_interval_s=5)
    tick_calls = []
    monkeypatch.setattr(worker.Worker, "tick", lambda self: tick_calls.append(1))

    sleep_calls = []

    class _StopLoop(Exception):
        pass

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise _StopLoop

    monkeypatch.setattr(worker.time, "sleep", fake_sleep)

    w = worker.Worker(config=config, spawner=FakeSpawner())
    with pytest.raises(_StopLoop):
        w.loop()

    assert tick_calls == [1]
    assert sleep_calls == [5.0]


def test_main_worker_command_runs_worker_loop(tmp_path, monkeypatch):
    from clipper.__main__ import main

    config = _config(tmp_path)
    monkeypatch.setattr("clipper.__main__.load_config", lambda path="config.toml": config)

    built = {}

    class FakeWorker:
        def __init__(self, *, config):
            built["config"] = config

        def loop(self):
            built["looped"] = True

    monkeypatch.setattr("clipper.worker.Worker", FakeWorker)

    exit_code = main(["worker"])

    assert exit_code == 0
    assert built["config"] is config
    assert built["looped"] is True


def test_main_serve_launches_worker_subprocess_and_stops_it_at_exit(tmp_path, monkeypatch):
    from clipper.__main__ import main

    config = Config(mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")
    monkeypatch.setattr("clipper.__main__.load_config", lambda path="config.toml": config)
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: None)

    process = FakeProcess()
    spawner = FakeSpawner(process)
    monkeypatch.setattr("clipper.__main__._popen", spawner)

    exit_code = main(["serve"])

    assert exit_code == 0
    assert spawner.calls == [[sys.executable, "-m", "clipper", "worker"]]
    assert process.terminate_calls == 1


# --------------------------------------------------------------------------
# TASK-ded3 : verrou inter-processus sur state/queue.json
# --------------------------------------------------------------------------


def _enqueue_many(config, prefix, n):
    for i in range(n):
        worker.enqueue(f"{prefix}{i:02d}", None, "render", config=config)


def test_enqueue_from_two_processes_loses_no_entry(tmp_path):
    import multiprocessing

    config = _config(tmp_path)
    ctx = multiprocessing.get_context("fork" if sys.platform != "win32" else "spawn")
    procs = [ctx.Process(target=_enqueue_many, args=(config, prefix, 20)) for prefix in ("a", "b")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
        assert p.exitcode == 0

    ids = sorted(e["video_id"] for e in _queue(config))
    assert ids == sorted([f"a{i:02d}" for i in range(20)] + [f"b{i:02d}" for i in range(20)])


def test_queue_write_goes_through_a_temp_file_and_os_replace(tmp_path, monkeypatch):
    config = _config(tmp_path)
    replaced = []
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda src, dst: (replaced.append((str(src), str(dst))), real_replace(src, dst))[1])

    worker.enqueue("AAAAAAAAAAA", None, "render", config=config)

    assert len(replaced) == 1
    src, dst = replaced[0]
    assert src != dst and dst == str(worker._queue_path(config))
    assert not os.path.exists(src)


# --------------------------------------------------------------------------
# (5) surveillance des chaines (TASK-7508, SPEC-fc0c §5)
# --------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402


class _WatchLister:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, source_url: str) -> list[dict]:
        self.calls.append(source_url)
        return [{"video_id": VIDEO_A, "url": URL_A, "title": "Direct", "duration_s": 7200,
                 "published_at": "2026-01-01T20:00:00+00:00"}]


def _watch_env(tmp_path, channels: dict[str, tuple[bool, int]]) -> Config:
    """Un preset par chaine ``nom -> (watch, watch_interval_s)``, un config.toml de base."""
    presets = tmp_path / "presets"
    presets.mkdir()
    base = tmp_path / "config.toml"
    base.write_text('mode = "review"\n', encoding="utf-8")
    for name, (on, interval) in channels.items():
        (presets / f"{name}.toml").write_text(
            f'[channel]\nsource_url = "https://example.test/{name}/videos"\nwatch = {str(on).lower()}\n'
            f"watch_interval_s = {interval}\nmode = \"review\"\n", encoding="utf-8")
    return Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={
            "worker": {"queue_path": str(tmp_path / "state" / "queue.json")},
            "watch": {"state_dir": str(tmp_path / "state" / "watch"),
                      "presets_dir": str(presets), "base_config": str(base)},
        },
    )


def _write_watch_state(tmp_path, name: str, checked_at: datetime | None) -> None:
    path = tmp_path / "state" / "watch" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checked_at": checked_at.isoformat() if checked_at else None,
                                "seen": [], "pending": [], "last_error": None}), encoding="utf-8")


def test_tick_checks_watched_channel_whose_interval_has_elapsed(tmp_path):
    config = _watch_env(tmp_path, {"ma_chaine": (True, 1800)})
    _write_watch_state(tmp_path, "ma_chaine", datetime.now(timezone.utc) - timedelta(seconds=1801))
    lister = _WatchLister()

    worker.Worker(config=config, spawner=FakeSpawner(), watch_lister=lister).tick()

    assert lister.calls == ["https://example.test/ma_chaine/videos"]
    state = json.loads((tmp_path / "state" / "watch" / "ma_chaine.json").read_text(encoding="utf-8"))
    assert [v["video_id"] for v in state["pending"]] == [VIDEO_A]


def test_tick_checks_a_watched_channel_never_checked(tmp_path):
    config = _watch_env(tmp_path, {"ma_chaine": (True, 1800)})
    lister = _WatchLister()

    worker.Worker(config=config, spawner=FakeSpawner(), watch_lister=lister).tick()

    assert len(lister.calls) == 1


def test_tick_skips_a_channel_checked_within_its_interval(tmp_path):
    config = _watch_env(tmp_path, {"ma_chaine": (True, 1800)})
    _write_watch_state(tmp_path, "ma_chaine", datetime.now(timezone.utc) - timedelta(seconds=600))
    lister = _WatchLister()

    worker.Worker(config=config, spawner=FakeSpawner(), watch_lister=lister).tick()

    assert lister.calls == []


def test_tick_skips_channels_with_watch_false(tmp_path):
    config = _watch_env(tmp_path, {"ma_chaine": (False, 1800)})
    lister = _WatchLister()

    worker.Worker(config=config, spawner=FakeSpawner(), watch_lister=lister).tick()

    assert lister.calls == []


def test_tick_checks_watched_channels_even_while_a_child_runs(tmp_path):
    config = _watch_env(tmp_path, {"ma_chaine": (True, 1800)})
    _write_queue(config, [{"id": "e1", "video_id": VIDEO_B, "url": URL_B, "channel": None, "action": "run",
                           "force_steps": [], "enqueued_at": "2026-01-01T00:00:00+00:00",
                           "status": "waiting", "pid": None}])
    lister = _WatchLister()
    w = worker.Worker(config=config, spawner=FakeSpawner(), watch_lister=lister)
    w.tick()  # lance l'enfant, premier check
    _write_watch_state(tmp_path, "ma_chaine", datetime.now(timezone.utc) - timedelta(seconds=1801))

    w.tick()  # l'enfant vit toujours

    assert len(lister.calls) == 2


def test_tick_logs_a_broken_preset_instead_of_crashing(tmp_path, caplog):
    config = _watch_env(tmp_path, {"ma_chaine": (True, 1800)})
    (tmp_path / "presets" / "cassee.toml").write_text("[channel\n", encoding="utf-8")
    lister = _WatchLister()

    with caplog.at_level("ERROR"):
        worker.Worker(config=config, spawner=FakeSpawner(), watch_lister=lister).tick()

    assert "cassee" in caplog.text


# --------------------------------------------------------------------------
# TASK-a40d : battement du worker (voyant « worker actif / arrêté » du tableau de bord)
# --------------------------------------------------------------------------


def _hb_config(tmp_path, **worker_overrides) -> Config:
    return _config(tmp_path, **worker_overrides)


def test_worker_defaults_declare_the_heartbeat_settings():
    assert worker.CONFIG_DEFAULTS["heartbeat_interval_s"] > 0
    assert worker.heartbeat_path(_config(Path("x"))) == Path("x") / "state" / "worker.json"


def test_tick_writes_a_heartbeat_with_pid_and_timestamp(tmp_path):
    config = _hb_config(tmp_path)

    worker.Worker(config=config, spawner=FakeSpawner(FakeProcess())).tick()

    beat = json.loads((tmp_path / "state" / "worker.json").read_text(encoding="utf-8"))
    assert beat["pid"] == os.getpid()
    assert datetime.fromisoformat(beat["at"]).tzinfo is not None


def test_heartbeat_is_rewritten_only_once_the_interval_has_passed(tmp_path, monkeypatch):
    config = _hb_config(tmp_path, heartbeat_interval_s=5)
    path = tmp_path / "state" / "worker.json"
    clock = {"t": 1000.0}
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock["t"])
    w = worker.Worker(config=config, spawner=FakeSpawner(FakeProcess()))

    w.tick()
    first = path.read_text(encoding="utf-8")
    path.unlink()
    clock["t"] += 2
    w.tick()
    assert not path.exists()
    clock["t"] += 4
    w.tick()
    assert path.exists() and first


def test_read_heartbeat_reports_active_stale_and_stopped(tmp_path):
    config = _hb_config(tmp_path, heartbeat_interval_s=5)
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    assert worker.read_heartbeat(config, now=now)["state"] == "stopped"

    path = tmp_path / "state" / "worker.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": os.getpid(), "at": (now - timedelta(seconds=4)).isoformat()}), encoding="utf-8")
    active = worker.read_heartbeat(config, now=now)
    assert active["state"] == "active" and active["pid"] == os.getpid() and active["age_s"] == 4

    path.write_text(json.dumps({"pid": os.getpid(), "at": (now - timedelta(seconds=60)).isoformat()}), encoding="utf-8")
    stale = worker.read_heartbeat(config, now=now)
    assert stale["state"] == "stale" and "périmé" in stale["reason"]
    assert stale["command"] == "python -m clipper worker"


def test_read_heartbeat_refuses_an_unreadable_file_in_french(tmp_path):
    config = _hb_config(tmp_path)
    path = tmp_path / "state" / "worker.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{pas du json", encoding="utf-8")

    with pytest.raises(worker.WorkerError, match="battement"):
        worker.read_heartbeat(config)


def test_heartbeat_with_a_dead_pid_is_stopped_even_if_recent(tmp_path, monkeypatch):
    config = _hb_config(tmp_path)
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    path = tmp_path / "state" / "worker.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": 99999, "at": now.isoformat()}), encoding="utf-8")
    monkeypatch.setattr(worker, "_pid_alive", lambda pid: False)

    assert worker.read_heartbeat(config, now=now)["state"] == "stopped"
