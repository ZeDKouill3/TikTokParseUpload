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
        sys.executable, "-m", "clipper",
        "--config", "presets/ma_chaine.toml",
        "run", URL_A,
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
# TASK-6a1b : --config avant la sous-commande ; un enfant en echec reste visible
# --------------------------------------------------------------------------


def _parse_built(entry: dict):
    from clipper.__main__ import build_parser

    cmd = worker._build_command(entry)
    assert cmd[:3] == [sys.executable, "-m", "clipper"]
    return build_parser().parse_args(cmd[3:])


def _cmd_entry(action: str = "run", channel: str | None = "ma_chaine", force_steps=None) -> dict:
    return {
        "video_id": VIDEO_A, "url": URL_A if action == "run" else VIDEO_A, "channel": channel,
        "action": action, "force_steps": force_steps or [],
    }


def test_build_command_is_accepted_by_the_real_parser_with_channel(tmp_path):
    args = _parse_built(_cmd_entry("run", "ma_chaine"))
    assert (args.config, args.command, args.url) == ("presets/ma_chaine.toml", "run", URL_A)


def test_build_command_is_accepted_by_the_real_parser_without_channel(tmp_path):
    args = _parse_built(_cmd_entry("run", None))
    assert (args.config, args.command, args.url) == (None, "run", URL_A)


def test_build_command_render_with_channel_and_force_step_is_accepted(tmp_path):
    args = _parse_built(_cmd_entry("render", "ma_chaine", ["parts", "render"]))
    assert (args.config, args.command, args.video_id) == ("presets/ma_chaine.toml", "render", VIDEO_A)
    assert args.force_step == ["parts", "render"]


def test_build_command_run_without_channel_with_force_step_is_accepted(tmp_path):
    args = _parse_built(_cmd_entry("run", None, ["parts"]))
    assert (args.config, args.command, args.url, args.force_step) == (None, "run", URL_A, ["parts"])


class _LoggingSpawner(FakeSpawner):
    """Simule un enfant qui ecrit sa sortie d'erreur dans le journal du worker."""

    def __init__(self, config: Config, output: str):
        super().__init__()
        self._config, self._output = config, output

    def __call__(self, cmd):
        log_path = worker.log_path(VIDEO_A, self._config)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(self._output, encoding="utf-8")
        return super().__call__(cmd)


def _fail_child(config: Config, output: str, code: int = 2, *, queue_second: bool = False):
    worker.enqueue(URL_A, "ma_chaine", "run", config=config)
    if queue_second:
        worker.enqueue(URL_B, None, "run", config=config)
    spawner = _LoggingSpawner(config, output)
    w = worker.Worker(config=config, spawner=spawner)
    w.tick()
    spawner.process.finish(code)
    w.tick()
    return w, spawner


def test_failed_child_without_pipeline_state_creates_a_failed_state_with_code_and_stderr_tail(tmp_path):
    config = _config(tmp_path)
    output = "ligne 1\n" + "clipper: error: unrecognized arguments: --config presets/ma_chaine.toml\n"

    _fail_child(config, output, code=2)

    state = pipeline.load_state(VIDEO_A, config=config)
    assert state["status"] == "failed"
    assert "2" in state["reason"]
    assert "unrecognized arguments: --config presets/ma_chaine.toml" in state["reason"]
    assert state["source_url"] == URL_A
    assert state["channel"] == "ma_chaine"
    assert _queue(config) == []


def test_failed_child_reason_keeps_only_the_end_of_a_long_output(tmp_path):
    config = _config(tmp_path)
    output = "".join(f"ligne {i}\n" for i in range(500))

    _fail_child(config, output, code=1)

    reason = pipeline.load_state(VIDEO_A, config=config)["reason"]
    assert "ligne 499" in reason
    assert "ligne 0\n" not in reason
    assert len(reason) < 4000


def test_failed_child_output_is_kept_in_the_log_file(tmp_path):
    config = _config(tmp_path)

    _fail_child(config, "boum\n", code=3)

    log_file = worker.log_path(VIDEO_A, config)
    assert log_file == config.workspace_dir / VIDEO_A / "worker.log"
    assert log_file.read_text(encoding="utf-8") == "boum\n"
    assert str(log_file) in pipeline.load_state(VIDEO_A, config=config)["reason"]


def test_failed_child_overrides_a_stale_state_left_running(tmp_path):
    config = _config(tmp_path)
    _pipeline_state(VIDEO_A, config, status="running")

    _fail_child(config, "kaboom\n", code=1)

    state = pipeline.load_state(VIDEO_A, config=config)
    assert state["status"] == "failed"
    assert "kaboom" in state["reason"]


def test_failed_child_clears_dismissed_at_so_the_failure_shows(tmp_path):
    config = _config(tmp_path)
    state = pipeline.new_state(VIDEO_A, URL_A, "auto")
    state["dismissed_at"] = "2026-01-01T00:00:00+00:00"
    pipeline.save_state(state, config=config)

    _fail_child(config, "oups\n", code=1)

    assert "dismissed_at" not in pipeline.load_state(VIDEO_A, config=config)


def test_failed_child_keeps_the_reason_the_pipeline_wrote_itself(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)
    spawner = FakeSpawner()
    w = worker.Worker(config=config, spawner=spawner)
    w.tick()
    state = pipeline.new_state(VIDEO_A, URL_A, "auto")
    state.update(status="failed", reason="download : video privee")
    pipeline.save_state(state, config=config)  # l'enfant a ecrit son propre echec
    spawner.process.finish(1)
    w.tick()

    assert pipeline.load_state(VIDEO_A, config=config)["reason"] == "download : video privee"
    assert _queue(config) == []


def test_failed_child_does_not_block_the_next_cmd_entry(tmp_path):
    config = _config(tmp_path)

    _, spawner = _fail_child(config, "x\n", code=1, queue_second=True)

    assert len(spawner.calls) == 2
    assert [e["video_id"] for e in _queue(config)] == [VIDEO_B]


def test_child_exiting_zero_writes_no_failure(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)
    spawner = FakeSpawner()
    w = worker.Worker(config=config, spawner=spawner)
    w.tick()
    spawner.process.finish(0)
    w.tick()

    assert _queue(config) == []
    assert not (config.workspace_dir / VIDEO_A / "pipeline.json").exists()


def test_default_spawner_writes_child_output_to_the_log_file(tmp_path):
    config = _config(tmp_path)
    worker.enqueue(URL_A, None, "run", config=config)
    w = worker.Worker(config=config)  # vrai subprocess.Popen
    w._spawn = lambda entry, cmd: w._popen_logged(entry, [sys.executable, "-c", "import sys; sys.stderr.write('fin triste'); sys.exit(7)"])
    w.tick()
    w._process.wait(timeout=30)
    w.tick()

    state = pipeline.load_state(VIDEO_A, config=config)
    assert state["status"] == "failed"
    assert "7" in state["reason"] and "fin triste" in state["reason"]
    assert "fin triste" in worker.log_path(VIDEO_A, config).read_text(encoding="utf-8")


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


# --------------------------------------------------------------------------
# TASK-0b78 : le worker publie les entrees dues sur TikTok (SPEC-9225 R3, R4, R6)
# La publication est injectee (fausse) : aucun navigateur, aucun TikTok.
# --------------------------------------------------------------------------

import logging  # noqa: E402

from clipper import accounts as accounts_mod, browser, publish, tiktok  # noqa: E402

ACCOUNT = "ab12cd"
LINK = "https://example.invalid/@ma_chaine/video/7300000000000000001"
_WEEK = "".join(f'[[channel.slots]]\nday = "{d}"\ntime = "09:00"\n' for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"))


_CONNECTED = {"state": "connected", "checked_at": "2026-10-01T10:00:00+00:00", "expires_at": None}


class FakeLogin:
    """Remplace browser.login_state : connexion simulee par compte (defaut : connecte), jamais de cookie lu."""

    def __init__(self, **states):
        self.states, self.calls = states, []

    def __call__(self, account, *, config=None, now=None):
        self.calls.append(account)
        state = self.states.get(account, "connected")
        if isinstance(state, Exception):
            raise state
        return {"state": state, "checked_at": "2026-10-01T10:00:00+00:00", "expires_at": None}


class FakePublisher:
    """Remplace tiktok.publish : enregistre les appels, rend un resultat ou leve ``error``."""

    def __init__(self, error=None, state="published", during=None):
        self.calls, self.error, self.state, self.during = [], error, state, during

    def __call__(self, clip, account, *, mode, schedule_at=None, config=None, on_tick=None, **kwargs):
        self.calls.append({"clip": clip, "account": account, "mode": mode, "schedule_at": schedule_at, "on_tick": on_tick,
                           **kwargs})
        if self.during is not None:
            self.during()
        if self.error is not None:
            raise self.error
        scheduled = mode == "scheduled"
        return {"post_url": None if scheduled else LINK, "post_id": None if scheduled else "7300000000000000001",
                "state": "scheduled_on_tiktok" if scheduled else "published",
                "publish_at": (schedule_at if scheduled else datetime.now(timezone.utc)).isoformat(), "note": None}


def _pub_env(tmp_path, monkeypatch, *, tiktok_settings=None, account=ACCOUNT, channels=("ma_chaine",)):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text('mode = "review"\n', encoding="utf-8")
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "accounts.json").write_text(
        json.dumps({"accounts": [{"id": ACCOUNT, "label": "A", "ready_to_publish": True, "login": _CONNECTED},
                                 {"id": "ef34ab", "label": "B", "ready_to_publish": True, "login": _CONNECTED}]}),
        encoding="utf-8")
    presets = tmp_path / "presets"
    presets.mkdir(exist_ok=True)
    for i, name in enumerate(channels):
        acc = f'tiktok_account = "{["ab12cd", "ef34ab"][i]}"\n' if account else ""
        (presets / f"{name}.toml").write_text(f'[channel]\ntimezone = "UTC"\n{acc}{_WEEK}', encoding="utf-8")
    return Config(
        mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={
            "worker": {"queue_path": str(tmp_path / "state" / "queue.json")},
            "watch": {"presets_dir": str(presets), "base_config": str(tmp_path / "config.toml")},
            "tiktok": tiktok_settings or {},
        })


def _seed(tmp_path, channel, clip_id, slot_at, *, status="scheduled", video_id="aaaaaaaaaaa", **extra):
    out = tmp_path / "output" / video_id
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{clip_id}.mp4").write_bytes(b"mp4")
    (out / f"{clip_id}.json").write_text(json.dumps({
        "video_id": video_id, "clip_id": clip_id, "caption": f"legende {clip_id}", "hashtags": ["#a", "#b"],
        "ready": True}), encoding="utf-8")
    path = tmp_path / "state" / "publish" / f"{channel}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append({
        "video_id": video_id, "clip_id": clip_id, "series_id": None, "part": None, "status": status,
        "slot_at": slot_at.isoformat() if slot_at else None, "decided_at": "2026-01-01T00:00:00+00:00",
        "published_at": None, "error": None, **extra})
    path.write_text(json.dumps(entries), encoding="utf-8")


def _entries(tmp_path, channel="ma_chaine"):
    return json.loads((tmp_path / "state" / "publish" / f"{channel}.json").read_text(encoding="utf-8"))


def _pub_worker(config, publisher, login=None):
    return worker.Worker(config=config, spawner=FakeSpawner(), publisher=publisher, login_checker=login or FakeLogin())


def _recheck(account=ACCOUNT):
    """L'utilisateur clique « J'ai regle le probleme » apres un arret R4 : la case suit la connexion (SPEC-e500 R3)."""
    accounts_mod.clear_halt(Config(mode="review", workspace_dir=Path("workspace"), output_dir=Path("output")), account)


def _ago(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


def test_tick_publishes_a_due_immediate_entry_with_mp4_caption_and_hashtags(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert len(pub.calls) == 1
    call = pub.calls[0]
    assert (call["account"], call["mode"], call["schedule_at"]) == (ACCOUNT, "immediate", None)
    assert call["clip"] == {"video_path": tmp_path / "output" / "aaaaaaaaaaa" / "01.mp4",
                            "caption": "legende 01", "hashtags": ["#a", "#b"]}
    entry = _entries(tmp_path)[0]
    assert entry["status"] == "published" and entry["tiktok_state"] == "published"
    assert (entry["post_url"], entry["post_id"]) == (LINK, "7300000000000000001")
    sidecar = json.loads((tmp_path / "output" / "aaaaaaaaaaa" / "01.json").read_text(encoding="utf-8"))
    assert sidecar["tiktok_post"]["url"] == LINK and sidecar["tiktok_post"]["account"] == ACCOUNT
    assert callable(call["on_tick"])  # le battement du worker continue pendant la publication


def test_tick_leaves_an_immediate_entry_whose_slot_is_not_reached(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", datetime.now(timezone.utc) + timedelta(hours=2))
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert pub.calls == [] and _entries(tmp_path)[0]["status"] == "scheduled"


def test_tick_ignores_entries_that_are_not_scheduled(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    for i, status in enumerate(("approved", "rejected", "published", "failed")):
        _seed(tmp_path, "ma_chaine", f"0{i}", _ago(minutes=1), status=status)
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert pub.calls == []


def test_scheduled_mode_publishes_once_the_date_is_inside_the_schedule_window(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"publish_mode": "scheduled"})
    inside = datetime.now(timezone.utc) + timedelta(days=3)
    outside = datetime.now(timezone.utc) + timedelta(days=11)
    _seed(tmp_path, "ma_chaine", "01", inside)
    _seed(tmp_path, "ma_chaine", "02", outside)
    pub = FakePublisher()
    w = _pub_worker(config, pub)

    w.tick()
    w.tick()

    assert [(c["mode"], c["schedule_at"]) for c in pub.calls] == [("scheduled", inside.replace(microsecond=inside.microsecond))]
    first, second = _entries(tmp_path)
    assert first["status"] == "published" and first["tiktok_state"] == "scheduled_on_tiktok"
    assert first["tiktok_publish_at"] == inside.isoformat()
    assert second["status"] == "scheduled"  # hors fenetre : attend


def test_an_entry_publish_mode_overrides_the_config_mode(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)  # config : immediate
    slot = datetime.now(timezone.utc) + timedelta(days=2)
    _seed(tmp_path, "ma_chaine", "01", slot, publish_mode="scheduled")
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert [c["mode"] for c in pub.calls] == ["scheduled"]


def test_the_worker_publishes_one_entry_per_tick_one_account_at_a_time(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, channels=("ma_chaine", "autre"),
                      tiktok_settings={"max_posts_per_day": 5, "min_gap_minutes": 0})
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=3))
    _seed(tmp_path, "ma_chaine", "02", _ago(minutes=2))
    _seed(tmp_path, "autre", "03", _ago(minutes=1), video_id="bbbbbbbbbbb")
    pub = FakePublisher()
    w = _pub_worker(config, pub)

    w.tick()
    assert [c["clip"]["caption"] for c in pub.calls] == ["legende 01"]
    w.tick()
    w.tick()
    assert [c["clip"]["caption"] for c in pub.calls] == ["legende 01", "legende 02", "legende 03"]
    assert [c["account"] for c in pub.calls] == [ACCOUNT, ACCOUNT, "ef34ab"]


def test_a_channel_without_a_tiktok_account_fails_explicitly_and_does_not_publish(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, account=None)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert pub.calls == []
    entry = _entries(tmp_path)[0]
    assert entry["status"] == "failed"
    assert "tiktok_account" in entry["error"] and "ma_chaine" in entry["error"]
    events = tiktok.read_events(config=config)
    assert events[-1]["level"] == "error" and "tiktok_account" in events[-1]["reason"]


@pytest.mark.parametrize("code, reason", [
    ("captcha", "captcha détecté"),
    ("verification", "vérification de compte demandée"),
    ("login", "connexion expirée"),
    ("element_missing", "élément attendu absent après 30 s : caption_editor"),
    ("unexpected_page", "page inattendue : https://exemple.invalid/erreur"),
])
def test_r4_a_stop_fails_the_entry_with_reason_and_capture_halts_the_account_and_notifies(tmp_path, monkeypatch, code, reason):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"max_posts_per_day": 5, "min_gap_minutes": 0})
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=2))
    _seed(tmp_path, "ma_chaine", "02", _ago(minutes=1))
    capture = tmp_path / "state" / "browser" / ACCOUNT / "captures" / f"x-{code}.png"
    pub = FakePublisher(error=tiktok.TikTokStop(code, reason, capture))
    w = _pub_worker(config, pub)

    w.tick()

    first, second = _entries(tmp_path)
    assert first["status"] == "failed" and first["error"] == reason
    assert first["capture"] == str(capture) and first["halted"] is True
    assert second["status"] == "scheduled"  # remise en attente, rien de publie derriere
    event = tiktok.read_events(config=config)[-1]
    assert (event["level"], event["account"], event["reason"], event["capture"]) == ("error", ACCOUNT, reason, str(capture))
    assert (event["channel"], event["video_id"], event["clip_id"]) == ("ma_chaine", "aaaaaaaaaaa", "01")

    pub.error = None
    w.tick()  # compte arrete : l'entree suivante n'est pas tentee
    assert len(pub.calls) == 1

    publish.retry("aaaaaaaaaaa", "01", "ma_chaine")  # bouton Reessayer
    _recheck()  # l'arret a decoche la case : elle se recoche a la main
    w.tick()
    assert len(pub.calls) == 2 and _entries(tmp_path)[0]["status"] == "published"


def test_a_browser_error_fails_and_halts_a_tiktok_error_only_fails_the_entry(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=2))
    w = _pub_worker(config, FakePublisher(error=browser.BrowserError("Chrome est introuvable")))
    w.tick()
    entry = _entries(tmp_path)[0]
    assert entry["status"] == "failed" and "Chrome est introuvable" in entry["error"] and entry["halted"] is True

    publish.retry("aaaaaaaaaaa", "01", "ma_chaine")
    _recheck()
    w.publisher = FakePublisher(error=tiktok.TikTokError("programmation refusée : trop loin"))
    w.tick()
    entry = _entries(tmp_path)[0]
    assert entry["status"] == "failed" and "trop loin" in entry["error"] and entry["halted"] is False


def test_an_unexpected_error_is_logged_and_fails_the_entry_instead_of_killing_the_worker(tmp_path, monkeypatch, caplog):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))

    with caplog.at_level(logging.ERROR):
        _pub_worker(config, FakePublisher(error=RuntimeError("boum"))).tick()

    entry = _entries(tmp_path)[0]
    assert entry["status"] == "failed" and "RuntimeError" in entry["error"] and "boum" in entry["error"]
    assert "boum" in caplog.text


def test_r6_posts_per_day_cap_postpones_to_the_next_free_slot_and_logs_it(tmp_path, monkeypatch, caplog):
    config = _pub_env(tmp_path, monkeypatch)  # 1 post par jour, 480 min d'ecart
    now = datetime.now(timezone.utc)
    _seed(tmp_path, "ma_chaine", "00", _ago(hours=0, seconds=1), status="published",
          tiktok_publish_at=(now - timedelta(seconds=1)).isoformat(), published_at=now.isoformat())
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()

    with caplog.at_level(logging.WARNING):
        _pub_worker(config, pub).tick()

    assert pub.calls == []
    entry = next(e for e in _entries(tmp_path) if e["clip_id"] == "01")
    assert entry["status"] == "scheduled"
    new_slot = datetime.fromisoformat(entry["slot_at"])
    assert new_slot > now and new_slot.date() != now.date()
    assert "plafond de 1 publication(s) par jour" in entry["postponed_reason"]
    assert "reporté" in caplog.text and "01" in caplog.text


def test_r6_min_gap_postpones_even_when_the_daily_cap_is_not_reached(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"max_posts_per_day": 9, "min_gap_minutes": 600})
    now = datetime.now(timezone.utc)
    _seed(tmp_path, "ma_chaine", "00", _ago(minutes=5), status="published",
          tiktok_publish_at=(now - timedelta(minutes=5)).isoformat(), published_at=now.isoformat())
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert pub.calls == []
    entry = next(e for e in _entries(tmp_path) if e["clip_id"] == "01")
    assert "600 minutes" in entry["postponed_reason"]
    assert datetime.fromisoformat(entry["slot_at"]) >= now + timedelta(minutes=595)


def test_r6_a_published_post_counts_for_the_account_across_channels(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    (tmp_path / "presets" / "autre.toml").write_text(
        f'[channel]\ntimezone = "UTC"\ntiktok_account = "{ACCOUNT}"\n{_WEEK}', encoding="utf-8")
    now = datetime.now(timezone.utc)
    _seed(tmp_path, "autre", "00", _ago(minutes=5), status="published", video_id="bbbbbbbbbbb",
          tiktok_publish_at=(now - timedelta(seconds=5)).isoformat(), published_at=now.isoformat())
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert pub.calls == []


def test_a_broken_publish_file_is_logged_once_and_does_not_kill_the_worker(tmp_path, monkeypatch, caplog):
    config = _pub_env(tmp_path, monkeypatch)
    path = tmp_path / "state" / "publish" / "ma_chaine.json"
    path.parent.mkdir(parents=True)
    path.write_text('[{"video_id": "x"}]', encoding="utf-8")
    w = _pub_worker(config, FakePublisher())

    with caplog.at_level(logging.ERROR):
        w.tick()
        w.tick()

    assert caplog.text.count("publication TikTok impossible") == 1


# --------------------------------------------------------------------------
# Releve periodique des statistiques TikTok (SPEC-9225 R7)
# --------------------------------------------------------------------------


class FakeStatsFetcher:
    """Remplace tiktok.fetch_stats : enregistre les appels, ecrit un releve ou leve ``error``."""

    def __init__(self, tmp_path, error=None):
        self.tmp, self.calls, self.error = tmp_path, [], error

    def __call__(self, account, *, config=None, on_tick=None, **kwargs):
        self.calls.append({"account": account, "on_tick": on_tick})
        if self.error is not None:
            raise self.error
        path = self.tmp / "state" / "stats" / "tiktok" / f"{account}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"account": account, "fetched_at": datetime.now(timezone.utc).isoformat(),
                                    "posts": [], "error": None}), encoding="utf-8")
        return {"account": account}


def _stats_worker(config, fetcher):
    return worker.Worker(config=config, spawner=FakeSpawner(), publisher=FakePublisher(), stats_fetcher=fetcher,
                         login_checker=FakeLogin())


def _published_clip(tmp_path, clip_id, account=ACCOUNT, *, video_id="aaaaaaaaaaa", post_id="7300000000000000001"):
    out = tmp_path / "output" / video_id
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{clip_id}.json").write_text(json.dumps({
        "video_id": video_id, "clip_id": clip_id,
        "tiktok_post": {"url": LINK, "id": post_id, "state": "published", "account": account}}), encoding="utf-8")


def test_tick_fetches_the_stats_of_an_account_with_a_published_post_then_waits_the_interval(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _published_clip(tmp_path, "01")
    fetcher = FakeStatsFetcher(tmp_path)
    w = _stats_worker(config, fetcher)

    w.tick()
    w.tick()

    assert [c["account"] for c in fetcher.calls] == [ACCOUNT]  # une fois : le releve est recent
    assert callable(fetcher.calls[0]["on_tick"])  # le battement du worker continue pendant le releve


def test_tick_refetches_once_the_configured_interval_has_passed(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"stats_interval_h": 2})
    _published_clip(tmp_path, "01")
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    path = tmp_path / "state" / "stats" / "tiktok" / f"{ACCOUNT}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"account": ACCOUNT, "fetched_at": old, "posts": [], "error": None}), encoding="utf-8")
    fetcher = FakeStatsFetcher(tmp_path)

    _stats_worker(config, fetcher).tick()

    assert len(fetcher.calls) == 1


def test_tick_does_not_open_a_browser_for_an_account_with_nothing_to_measure(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    fetcher = FakeStatsFetcher(tmp_path)

    _stats_worker(config, fetcher).tick()

    assert fetcher.calls == []


def test_tick_skips_the_stats_of_an_account_halted_by_a_safe_stop(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"max_posts_per_day": 5, "min_gap_minutes": 0})
    _published_clip(tmp_path, "00", video_id="bbbbbbbbbbb")
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    w = worker.Worker(config=config, spawner=FakeSpawner(),
                      publisher=FakePublisher(error=tiktok.TikTokStop("captcha", "captcha détecté", None)),
                      stats_fetcher=FakeStatsFetcher(tmp_path), login_checker=FakeLogin())

    w.tick()  # la publication s'arrete sur captcha : compte arrete
    w.tick()

    assert w.stats_fetcher.calls == []


def test_tick_does_not_fetch_stats_in_the_tick_that_drove_a_publication(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"max_posts_per_day": 5, "min_gap_minutes": 0})
    _published_clip(tmp_path, "00", video_id="bbbbbbbbbbb")
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    fetcher = FakeStatsFetcher(tmp_path)
    pub = FakePublisher()
    w = worker.Worker(config=config, spawner=FakeSpawner(), publisher=pub, stats_fetcher=fetcher, login_checker=FakeLogin())

    w.tick()
    assert len(pub.calls) == 1 and fetcher.calls == []  # un seul pilotage du navigateur par iteration
    w.tick()
    assert len(fetcher.calls) == 1


def test_tick_fetches_one_account_per_iteration(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, channels=("ma_chaine", "autre"))
    _published_clip(tmp_path, "01")
    _published_clip(tmp_path, "02", account="ef34ab", video_id="bbbbbbbbbbb")
    fetcher = FakeStatsFetcher(tmp_path)
    w = _stats_worker(config, fetcher)

    w.tick()
    assert [c["account"] for c in fetcher.calls] == [ACCOUNT]
    w.tick()
    assert [c["account"] for c in fetcher.calls] == [ACCOUNT, "ef34ab"]


@pytest.mark.parametrize("error", [
    tiktok.TikTokStop("captcha", "captcha détecté : arrêt immédiat", None),
    browser.BrowserError("Chrome introuvable"),
    tiktok.TikTokError("réglage invalide"),
])
def test_a_failed_stats_fetch_is_logged_once_not_retried_every_tick_and_never_kills_the_worker(
        tmp_path, monkeypatch, caplog, error):
    config = _pub_env(tmp_path, monkeypatch)
    _published_clip(tmp_path, "01")
    fetcher = FakeStatsFetcher(tmp_path, error=error)
    w = _stats_worker(config, fetcher)

    with caplog.at_level(logging.ERROR):
        w.tick()
        w.tick()
        w.tick()

    assert len(fetcher.calls) == 1
    assert caplog.text.count("relevé des statistiques TikTok impossible") == 1
    assert str(error) in caplog.text


def test_an_unexpected_error_in_the_stats_fetch_is_logged_not_fatal(tmp_path, monkeypatch, caplog):
    config = _pub_env(tmp_path, monkeypatch)
    _published_clip(tmp_path, "01")
    w = _stats_worker(config, FakeStatsFetcher(tmp_path, error=RuntimeError("boom")))

    with caplog.at_level(logging.ERROR):
        w.tick()

    assert "boom" in caplog.text


# --------------------------------------------------------------------------
# SPEC-00d1 R2-R4, R6 : comptes prets, connexion verifiee, compte choisi par publication
# --------------------------------------------------------------------------

OTHER = "ef34ab"


def _set_account_state(tmp_path, account, **fields):
    path = tmp_path / "state" / "accounts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    next(a for a in data["accounts"] if a["id"] == account).update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")


def _account_state(tmp_path, account):
    data = json.loads((tmp_path / "state" / "accounts.json").read_text(encoding="utf-8"))
    return next(a for a in data["accounts"] if a["id"] == account)


def test_an_entry_whose_account_is_not_ready_is_not_attempted_and_waits_with_the_reason(tmp_path, monkeypatch, caplog):
    config = _pub_env(tmp_path, monkeypatch)
    _set_account_state(tmp_path, ACCOUNT, ready_to_publish=False)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub, login = FakePublisher(), FakeLogin()

    with caplog.at_level(logging.WARNING):
        _pub_worker(config, pub, login).tick()

    assert pub.calls == [] and login.calls == []  # ni publication, ni lecture de cookies pour un compte non prêt
    entry = _entries(tmp_path)[0]
    assert entry["status"] == "scheduled" and entry["error"] is None  # en attente, pas en échec
    assert "non prêt à publier" in entry["waiting_reason"] and "A" in entry["waiting_reason"]
    assert "non prêt à publier" in caplog.text
    event = tiktok.read_events(config=config)[-1]
    assert event["level"] == "warn" and event["account"] == ACCOUNT and event["clip_id"] == "01"


def test_a_not_ready_account_never_falls_back_to_another_account(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)  # le compte de la chaine (ab12cd) est prêt, l'autre non
    _set_account_state(tmp_path, OTHER, ready_to_publish=False)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1), account=OTHER)
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert pub.calls == []  # ni l'autre compte, ni celui de la chaine
    assert "non prêt à publier" in _entries(tmp_path)[0]["waiting_reason"]


def test_the_account_chosen_for_the_publication_is_the_one_the_worker_uses(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1), account=OTHER)  # la chaine pointe ab12cd
    pub, login = FakePublisher(), FakeLogin()

    _pub_worker(config, pub, login).tick()

    assert [c["account"] for c in pub.calls] == [OTHER]
    assert login.calls == [OTHER]  # c'est la connexion de CE compte qui est verifiee
    entry = _entries(tmp_path)[0]
    assert entry["status"] == "published" and entry["waiting_reason"] is None
    sidecar = json.loads((tmp_path / "output" / "aaaaaaaaaaa" / "01.json").read_text(encoding="utf-8"))
    assert sidecar["tiktok_post"]["account"] == OTHER


def test_an_entry_without_account_field_keeps_using_the_channel_account(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))  # file d'avant R4 : aucun champ account
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert [c["account"] for c in pub.calls] == [ACCOUNT]


def test_an_entry_with_an_unknown_account_waits_with_the_reason(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1), account="supprime")
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert pub.calls == []
    assert "introuvable" in _entries(tmp_path)[0]["waiting_reason"]


def test_a_waiting_entry_does_not_block_the_next_due_entry_of_a_ready_account(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"max_posts_per_day": 5, "min_gap_minutes": 0})
    _set_account_state(tmp_path, OTHER, ready_to_publish=False)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=3), account=OTHER)
    _seed(tmp_path, "ma_chaine", "02", _ago(minutes=2))
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert [c["clip"]["caption"] for c in pub.calls] == ["legende 02"]
    first, second = _entries(tmp_path)
    assert first["status"] == "scheduled" and first["waiting_reason"] and second["status"] == "published"


def test_the_entry_is_attempted_again_once_the_account_is_ready_and_the_reason_is_cleared(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _set_account_state(tmp_path, ACCOUNT, ready_to_publish=False)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()
    w = _pub_worker(config, pub)
    w.tick()
    assert pub.calls == [] and _entries(tmp_path)[0]["waiting_reason"]

    _recheck()
    w.tick()

    assert len(pub.calls) == 1 and _entries(tmp_path)[0]["status"] == "published"
    assert _entries(tmp_path)[0]["waiting_reason"] is None


def test_the_reason_is_logged_and_notified_once_not_at_every_tick(tmp_path, monkeypatch, caplog):
    config = _pub_env(tmp_path, monkeypatch)
    _set_account_state(tmp_path, ACCOUNT, ready_to_publish=False)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    w = _pub_worker(config, FakePublisher())

    with caplog.at_level(logging.WARNING):
        w.tick()
        w.tick()
        w.tick()

    assert caplog.text.count("publication en attente") == 1
    assert len(tiktok.read_events(config=config)) == 1


def test_the_connection_is_verified_before_each_publication(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"max_posts_per_day": 5, "min_gap_minutes": 0})
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=2))
    _seed(tmp_path, "ma_chaine", "02", _ago(minutes=1))
    login = FakeLogin()
    w = _pub_worker(config, FakePublisher(), login)

    w.tick()
    w.tick()

    assert login.calls == [ACCOUNT, ACCOUNT]


def test_an_expired_session_before_publishing_unticks_ready_and_the_entry_waits(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()

    _pub_worker(config, pub, FakeLogin(**{ACCOUNT: "expired"})).tick()

    assert pub.calls == []
    entry = _entries(tmp_path)[0]
    assert entry["status"] == "scheduled" and "session TikTok expirée" in entry["waiting_reason"]
    assert "décoché" in entry["waiting_reason"]
    stored = _account_state(tmp_path, ACCOUNT)
    assert stored["ready_to_publish"] is False and "décoché automatiquement" in stored["ready_note"]
    assert stored["login"]["state"] == "expired"


def test_a_never_connected_profile_before_publishing_waits_without_publishing(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()

    _pub_worker(config, pub, FakeLogin(**{ACCOUNT: "never"})).tick()

    assert pub.calls == [] and "non connecté à TikTok" in _entries(tmp_path)[0]["waiting_reason"]


def test_a_connection_that_cannot_be_verified_waits_with_the_error_and_nothing_is_published(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()
    login = FakeLogin(**{ACCOUNT: browser.BrowserError("cookies du profil illisibles : ferme la fenêtre Chrome")})

    _pub_worker(config, pub, login).tick()

    assert pub.calls == []
    entry = _entries(tmp_path)[0]
    assert entry["status"] == "scheduled" and "non vérifiable" in entry["waiting_reason"]
    assert "ferme la fenêtre Chrome" in entry["waiting_reason"]
    assert _account_state(tmp_path, ACCOUNT)["ready_to_publish"] is True  # pas de verification : pas de decochage


@pytest.mark.parametrize("error", [
    tiktok.TikTokStop("captcha", "captcha détecté", None),
    browser.BrowserError("Chrome est introuvable"),
    RuntimeError("boum"),
])
def test_an_r4_stop_unticks_ready_until_the_user_ticks_it_again(tmp_path, monkeypatch, caplog, error):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))

    with caplog.at_level(logging.WARNING):
        _pub_worker(config, FakePublisher(error=error)).tick()

    stored = _account_state(tmp_path, ACCOUNT)
    assert stored["ready_to_publish"] is False and "arrêt de publication" in stored["ready_note"]
    assert "prêt à publier" in caplog.text and "décoché" in caplog.text
    assert _account_state(tmp_path, OTHER)["ready_to_publish"] is True  # les autres comptes ne bougent pas


def test_an_error_that_does_not_halt_the_account_keeps_ready_ticked(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))

    _pub_worker(config, FakePublisher(error=tiktok.TikTokError("programmation refusée"))).tick()

    assert _account_state(tmp_path, ACCOUNT)["ready_to_publish"] is True
    assert _entries(tmp_path)[0]["failed_at"]  # l'echec est date


def test_a_halt_on_the_chosen_account_does_not_block_the_channel_account(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"max_posts_per_day": 5, "min_gap_minutes": 0})
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=2), account=OTHER)
    _seed(tmp_path, "ma_chaine", "02", _ago(minutes=1))
    pub = FakePublisher(error=tiktok.TikTokStop("captcha", "captcha détecté", None))
    w = _pub_worker(config, pub)

    w.tick()  # l'entree 01 (compte OTHER) s'arrete
    pub.error = None
    w.tick()

    assert [c["account"] for c in pub.calls] == [OTHER, ACCOUNT]
    assert _entries(tmp_path)[1]["status"] == "published"


# --------------------------------------------------------------------------
# SPEC-1ed3 R4 : publications pilotees depuis l'ecran Publication (entrees manuelles)
# --------------------------------------------------------------------------

NO_CHANNEL = "_sans_chaine"
_OPTIONS = {"visibility": "friends", "allow_comments": False, "allow_reuse": True, "ai_generated": True,
            "content_check": "wait"}


def _manual(tmp_path, clip_id, slot_at, *, channel=NO_CHANNEL, mode="immediate", account="ef34ab", options=None,
            **extra):
    _seed(tmp_path, channel, clip_id, slot_at, publish_mode=mode, account=account, manual=True,
          post_options=_OPTIONS if options is None else options, **extra)


def test_now_is_due_right_away_for_a_video_without_channel_and_transmits_the_post_options(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _manual(tmp_path, "01", datetime.now(timezone.utc))
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert len(pub.calls) == 1
    call = pub.calls[0]
    assert (call["account"], call["mode"], call["schedule_at"]) == ("ef34ab", "immediate", None)
    assert call["options"] == _OPTIONS  # reglages par post transmis a clipper.tiktok
    entry = _entries(tmp_path, NO_CHANNEL)[0]
    assert entry["status"] == "published" and entry["post_url"] == LINK and entry["in_progress_since"] is None


def test_an_entry_without_post_options_does_not_pass_options(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _seed(tmp_path, "ma_chaine", "01", _ago(minutes=1))
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert "options" not in pub.calls[0]


def test_the_entry_is_in_progress_while_the_browser_is_driven(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _manual(tmp_path, "01", datetime.now(timezone.utc))
    seen = []
    pub = FakePublisher(during=lambda: seen.append(_entries(tmp_path, NO_CHANNEL)[0].get("in_progress_since")))

    _pub_worker(config, pub).tick()

    assert seen and seen[0]  # « en cours » : ni modifiable ni annulable pendant le pilotage


def test_a_failed_publication_clears_in_progress_and_keeps_the_reason(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _manual(tmp_path, "01", datetime.now(timezone.utc))
    pub = FakePublisher(error=tiktok.TikTokStop("captcha", "captcha détecté", None))

    _pub_worker(config, pub).tick()

    entry = _entries(tmp_path, NO_CHANNEL)[0]
    assert entry["status"] == "failed" and entry["error"] == "captcha détecté" and entry["in_progress_since"] is None


def test_scheduled_inside_the_tiktok_window_is_scheduled_on_tiktok(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    when = datetime.now(timezone.utc) + timedelta(days=3)
    _manual(tmp_path, "01", when, mode="scheduled")
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert [(c["mode"], c["schedule_at"]) for c in pub.calls] == [("scheduled", when)]
    entry = _entries(tmp_path, NO_CHANNEL)[0]
    assert entry["status"] == "published" and entry["tiktok_state"] == "scheduled_on_tiktok"


def test_scheduled_beyond_the_window_is_kept_then_scheduled_once_the_date_enters_the_window(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"schedule_max_days": 1})
    far = datetime.now(timezone.utc) + timedelta(hours=30)
    _manual(tmp_path, "01", far, mode="scheduled")
    pub = FakePublisher()
    w = _pub_worker(config, pub)

    w.tick()
    assert pub.calls == [] and _entries(tmp_path, NO_CHANNEL)[0]["status"] == "scheduled"  # gardee par Clipper

    # le temps passe : la date entre dans la fenetre de TikTok (24 h)
    path = tmp_path / "state" / "publish" / f"{NO_CHANNEL}.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    near = datetime.now(timezone.utc) + timedelta(hours=20)
    entries[0]["slot_at"] = near.isoformat()
    path.write_text(json.dumps(entries), encoding="utf-8")
    w.tick()

    assert [(c["mode"], c["schedule_at"]) for c in pub.calls] == [("scheduled", near)]
    assert _entries(tmp_path, NO_CHANNEL)[0]["tiktok_state"] == "scheduled_on_tiktok"


def test_a_manual_entry_over_the_account_cap_waits_with_the_reason_and_is_never_moved(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch, tiktok_settings={"max_posts_per_day": 1, "min_gap_minutes": 0})
    _seed(tmp_path, "ma_chaine", "00", _ago(seconds=5), status="published", published_at=_ago(seconds=5).isoformat(),
          account="ef34ab")
    slot = datetime.now(timezone.utc)
    _manual(tmp_path, "01", slot)
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert pub.calls == []
    entry = _entries(tmp_path, NO_CHANNEL)[0]
    assert entry["status"] == "scheduled" and entry["slot_at"] == slot.isoformat()  # aucun report silencieux
    assert "plafond" in entry["waiting_reason"]


def test_a_manual_entry_of_an_account_not_ready_is_not_attempted(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _manual(tmp_path, "01", datetime.now(timezone.utc), account="inconnu")
    pub = FakePublisher()

    _pub_worker(config, pub).tick()

    assert pub.calls == []
    assert "inconnu" in _entries(tmp_path, NO_CHANNEL)[0]["waiting_reason"]


def test_starting_the_worker_fails_an_entry_left_in_progress(tmp_path, monkeypatch):
    config = _pub_env(tmp_path, monkeypatch)
    _manual(tmp_path, "01", datetime.now(timezone.utc), in_progress_since="2026-10-01T10:00:00+00:00")

    _pub_worker(config, FakePublisher())

    entry = _entries(tmp_path, NO_CHANNEL)[0]
    assert entry["status"] == "failed" and "interrompue" in entry["error"] and entry["in_progress_since"] is None
