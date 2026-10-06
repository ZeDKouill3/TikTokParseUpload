"""veille.py : relevé quotidien des sujets chauds (TASK-87cd, SPEC-bdd9 R1, R2, R4, R5).

Collecteurs injectés, ``tmp_path`` pour ``state/`` : aucun test ne touche le réseau.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from clipper import veille
from clipper.config import Config, load_config

NOW = datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc)  # 10:00 à Paris
TODAY = "2026-10-06"


def _make_config(tmp_path, **veille_table) -> Config:
    table = {
        "state_dir": str(tmp_path / "state" / "veille"),
        "twitch_client_id": "cid",
        "twitch_client_secret": "csecret",
        "youtube_api_key": "ykey",
        **veille_table,
    }
    return Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={
            "worker": {"queue_path": str(tmp_path / "state" / "queue.json")},
            "veille": table,
        },
    )


@pytest.fixture
def config(tmp_path):
    return _make_config(tmp_path)


def _sdir(tmp_path):
    return tmp_path / "state" / "veille"


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _vod(video_id, *, duration_s=7200, age_h=5, game="Jeu Alpha", source="twitch"):
    published = NOW - timedelta(hours=age_h)
    return {
        "video_id": video_id,
        "url": f"https://example.test/{video_id}",
        "title": f"Titre {video_id}",
        "channel_name": "streamer_a",
        "game_name": game,
        "duration_s": duration_s,
        "published_at": published.isoformat(),
        "view_count": 1000,
        "views_per_hour": 200.0,
    }


class Collector:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls = 0

    def __call__(self, settings):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _collectors(*, viewers=1000, players=5000, vods=(), videos=()):
    return {
        "twitch": Collector({"games": [{"name": "Jeu Alpha", "viewers_fr": viewers}], "vods": list(vods)}),
        "youtube": Collector({"videos": list(videos)}),
        "steam": Collector({"games": [{"appid": "42", "name": "Jeu  Alpha !", "players": players}]}),
    }


def _write_history(tmp_path, date, *, viewers, players):
    path = _sdir(tmp_path) / "history" / f"{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "date": date, "at": f"{date}T08:00:00+00:00",
        "twitch": {"jeu alpha": {"name": "Jeu Alpha", "viewers_fr": viewers}},
        "steam": {"42": {"name": "Jeu Alpha", "players": players}},
        "youtube": {},
    }), encoding="utf-8")


# --- R1 : réglages ---------------------------------------------------------


def test_config_defaults_are_exactly_r1():
    assert veille.CONFIG_DEFAULTS == {
        "enabled": False, "run_at": "07:00", "timezone": "Europe/Paris", "language": "fr",
        "region": "FR", "taste": "", "max_vods_per_day": 3, "best_clips_per_day": 3,
        "baseline_days": 7, "history_days": 90, "rise_min_pct": 50, "vod_min_duration_s": 1800,
        "vod_max_age_h": 36, "twitch_top_games": 20, "twitch_vods_per_game": 10,
        "youtube_max_results": 50, "youtube_min_duration_s": 600, "steam_top": 100,
        "twitch_client_id": "", "twitch_client_secret": "", "youtube_api_key": "",
        "state_dir": "state/veille", "http_timeout_s": 20,
    }


def test_load_config_accepts_veille_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[veille]\nenabled = true\nrun_at = "06:30"\n', encoding="utf-8")
    section = load_config(path).section("veille")
    assert section["enabled"] is True and section["run_at"] == "06:30"
    assert section["max_vods_per_day"] == 3


@pytest.mark.parametrize("table, key", [
    ({"max_vods_per_day": 0}, "max_vods_per_day"),
    ({"best_clips_per_day": 0}, "best_clips_per_day"),
    ({"baseline_days": 0}, "baseline_days"),
    ({"baseline_days": 10, "history_days": 9}, "history_days"),
    ({"run_at": "7h00"}, "run_at"),
    ({"run_at": "25:00"}, "run_at"),
])
def test_invalid_settings_raise_naming_the_key(tmp_path, table, key):
    config = _make_config(tmp_path, **table)
    with pytest.raises(veille.VeilleError, match=key):
        veille.collect(NOW, collectors=_collectors(), config=config)


# --- R2 / R3 : fichiers, erreurs par source -------------------------------


def test_collect_writes_history_and_day_files(tmp_path, config):
    veille.collect(NOW, collectors=_collectors(), config=config)
    history = _read(_sdir(tmp_path) / "history" / f"{TODAY}.json")
    assert history["date"] == TODAY
    assert history["twitch"] == {"jeu alpha": {"name": "Jeu Alpha", "viewers_fr": 1000}}
    assert history["steam"] == {"42": {"name": "Jeu  Alpha !", "players": 5000}}
    day = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    assert day["date"] == TODAY and day["started_at"] and day["finished_at"]
    assert {s: day["sources"][s]["status"] for s in ("twitch", "youtube", "steam")} == {
        "twitch": "ok", "youtube": "ok", "steam": "ok"}
    assert day["sources"]["twitch"]["error"] is None


def test_failing_collector_is_error_others_ok_nothing_raised(tmp_path, config):
    collectors = _collectors()
    collectors["youtube"] = Collector(error=RuntimeError("HTTP 500 boom"))
    veille.collect(NOW, collectors=collectors, config=config)
    day = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    assert day["sources"]["youtube"]["status"] == "error"
    assert "HTTP 500 boom" in day["sources"]["youtube"]["error"]
    assert day["sources"]["twitch"]["status"] == "ok"
    assert day["sources"]["steam"]["status"] == "ok"


@pytest.mark.parametrize("source, empty_key", [
    ("twitch", "twitch_client_id"),
    ("twitch", "twitch_client_secret"),
    ("youtube", "youtube_api_key"),
])
def test_missing_key_is_error_and_collector_not_called(tmp_path, source, empty_key):
    config = _make_config(tmp_path, **{empty_key: ""})
    collectors = _collectors()
    veille.collect(NOW, collectors=collectors, config=config)
    day = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    assert day["sources"][source]["status"] == "error"
    assert empty_key in day["sources"][source]["error"]
    assert "Réglages › Veille" in day["sources"][source]["error"]
    assert collectors[source].calls == 0


def test_steam_needs_no_key(tmp_path, config):
    collectors = _collectors()
    veille.collect(NOW, collectors=collectors, config=config)
    assert collectors["steam"].calls == 1


def test_secrets_never_written_to_state(tmp_path, config):
    veille.collect(NOW, collectors=_collectors(vods=[_vod("v1")]), config=config)
    for path in _sdir(tmp_path).rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "csecret" not in text and "ykey" not in text


# --- R4 : montée ------------------------------------------------------------


def test_delta_vs_mean_of_three_previous_days(tmp_path, config):
    _write_history(tmp_path, "2026-10-03", viewers=400, players=1000)
    _write_history(tmp_path, "2026-10-04", viewers=500, players=2000)
    _write_history(tmp_path, "2026-10-05", viewers=600, players=3000)
    veille.collect(NOW, collectors=_collectors(viewers=1000, players=5000), config=config)
    game = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")["games"][0]
    assert game["key"] == "jeu alpha"
    assert game["twitch_avg"] == 500 and game["steam_avg"] == 2000
    assert game["twitch_delta_pct"] == round((1000 - 500) / 500 * 100) == 100
    assert game["steam_delta_pct"] == round((5000 - 2000) / 2000 * 100) == 150
    assert game["baseline_days_available"] == 3


@pytest.mark.parametrize("previous", [0, 1])
def test_not_enough_history_gives_null_delta(tmp_path, config, previous):
    for i in range(previous):
        _write_history(tmp_path, f"2026-10-0{4 + i}", viewers=500, players=2000)
    veille.collect(NOW, collectors=_collectors(), config=config)
    game = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")["games"][0]
    assert game["twitch_delta_pct"] is None and game["steam_delta_pct"] is None
    assert game["baseline_days_available"] == previous


def test_twitch_game_without_steam_app_is_not_zero(tmp_path, config):
    collectors = _collectors()
    collectors["twitch"] = Collector({"games": [{"name": "Jéu Béta", "viewers_fr": 10}], "vods": []})
    veille.collect(NOW, collectors=collectors, config=config)
    game = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")["games"][0]
    assert game["steam_match"] is False
    assert game["steam_appid"] is None and game["steam_players"] is None
    assert game["steam_avg"] is None and game["steam_delta_pct"] is None


def test_steam_match_ignores_case_accents_punctuation(tmp_path, config):
    collectors = _collectors()
    collectors["twitch"] = Collector({"games": [{"name": "JEU  alpha", "viewers_fr": 10}], "vods": []})
    collectors["steam"] = Collector({"games": [{"appid": "7", "name": "Jeu: Alpha!", "players": 99}]})
    veille.collect(NOW, collectors=collectors, config=config)
    game = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")["games"][0]
    assert game["steam_match"] is True and game["steam_appid"] == "7" and game["steam_players"] == 99


# --- R5 : candidats ---------------------------------------------------------


def test_candidates_filtered_and_counted(tmp_path, config):
    (tmp_path / "workspace" / "w1").mkdir(parents=True)
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "queue.json").write_text(json.dumps([
        {"id": "q", "video_id": "q1", "url": "u", "channel": None, "action": "run", "status": "waiting"},
    ]), encoding="utf-8")
    (_sdir(tmp_path)).mkdir(parents=True)
    (_sdir(tmp_path) / "seen.json").write_text(json.dumps({
        "queued": [{"candidate_id": "twitch:s1", "video_id": "s1"}],
        "ignored": [{"candidate_id": "twitch:i1", "video_id": "i1"}],
    }), encoding="utf-8")
    vods = [
        _vod("ok1"), _vod("short", duration_s=60), _vod("old", age_h=100),
        _vod("w1"), _vod("q1"), _vod("s1"), _vod("i1"),
    ]
    veille.collect(NOW, collectors=_collectors(vods=vods), config=config)
    day = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    assert [c["id"] for c in day["candidates"]] == ["twitch:ok1"]
    assert day["excluded"] == {"too_short": 1, "too_old": 1, "already_known": 4}
    candidate = day["candidates"][0]
    assert candidate["source"] == "twitch" and candidate["video_id"] == "ok1"
    assert candidate["game_key"] == "jeu alpha" and candidate["duration_s"] == 7200


def test_youtube_candidates_use_youtube_min_duration(tmp_path, config):
    videos = [_vod("yt1", duration_s=700), _vod("yt2", duration_s=100)]
    veille.collect(NOW, collectors=_collectors(videos=videos), config=config)
    day = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    assert [c["id"] for c in day["candidates"]] == ["youtube:yt1"]
    assert day["excluded"]["too_short"] == 1


# --- rétention, fichiers illisibles ----------------------------------------


def test_old_history_files_are_pruned(tmp_path):
    config = _make_config(tmp_path, history_days=10)
    _write_history(tmp_path, "2026-09-20", viewers=1, players=1)  # 16 j : supprimé
    _write_history(tmp_path, "2026-09-30", viewers=1, players=1)  # 6 j : gardé
    veille.collect(NOW, collectors=_collectors(), config=config)
    names = sorted(p.name for p in (_sdir(tmp_path) / "history").glob("*.json"))
    assert names == ["2026-09-30.json", f"{TODAY}.json"]


@pytest.mark.parametrize("relpath", ["history/2026-10-05.json", "seen.json"])
def test_unreadable_state_file_raises_naming_it(tmp_path, config, relpath):
    path = _sdir(tmp_path) / relpath
    path.parent.mkdir(parents=True)
    path.write_text("{pas du json", encoding="utf-8")
    with pytest.raises(veille.VeilleError, match=path.name):
        veille.collect(NOW, collectors=_collectors(), config=config)


# ==========================================================================
# TASK-3225 : choix de Claude, exécution, actions, sélection (R6, R7)
# ==========================================================================

from clipper import llm  # noqa: E402
from clipper.llm.fake import FakeBackend  # noqa: E402

AFTER_RUN_AT = datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc)   # 08:00 à Paris
BEFORE_RUN_AT = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)  # 06:00 à Paris


def _day_state(*candidate_ids):
    return {
        "date": TODAY, "started_at": NOW.isoformat(), "finished_at": None, "sources": {},
        "games": [{"key": "jeu alpha", "name": "Jeu Alpha", "twitch_fr_viewers": 1000, "twitch_delta_pct": 120,
                   "steam_delta_pct": None}],
        "candidates": [{"id": cid, "source": "twitch", "video_id": cid.split(":")[1],
                        "url": f"https://youtu.be/{cid.split(':')[1]}",
                        "title": f"Titre {cid}", "channel_name": "streamer_a", "game_key": "jeu alpha",
                        "game_name": "Jeu Alpha", "duration_s": 7200, "published_at": NOW.isoformat(),
                        "view_count": 4321, "views_per_hour": 99.5,
                        "signals": {"twitch_delta_pct": 120, "steam_delta_pct": None}} for cid in candidate_ids],
        "excluded": {}, "llm": {"status": "skipped", "error": None, "model": None},
        "proposals": [], "skipped_note": "", "refresh_requested_at": None,
    }


def _picks(*ids, note=""):
    return {"picks": [{"candidate_id": i, "reason": f"raison {i}"} for i in ids], "skipped_note": note}


def test_decide_asks_claude_once_with_text_only_and_the_figures(tmp_path):
    config = _make_config(tmp_path, taste="j'aime les jeux de survie", max_vods_per_day=2)
    fake = FakeBackend([_picks("twitch:AAA", "twitch:BBB", note="le reste est trop long")])
    with llm.use_backend(fake):
        state = veille.decide(_day_state("twitch:AAA", "twitch:BBB", "twitch:CCC"), config)
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.usage == "veille" and call.images == []
    for text in ("j'aime les jeux de survie", "2", "twitch:AAA", "twitch:CCC", "4321", "99.5", "120"):
        assert text in call.prompt
    assert state["llm"]["status"] == "ok" and state["llm"]["error"] is None
    assert [(p["candidate_id"], p["rank"], p["status"]) for p in state["proposals"]] == [
        ("twitch:AAA", 1, "proposed"), ("twitch:BBB", 2, "proposed")]
    assert state["proposals"][0]["reason"] == "raison twitch:AAA"
    assert state["proposals"][0]["channel"] is None and state["proposals"][0]["queue_entry_id"] is None
    assert state["skipped_note"] == "le reste est trop long"


def test_decide_says_no_declared_preference_when_taste_is_empty(tmp_path):
    fake = FakeBackend([_picks()])
    with llm.use_backend(fake):
        state = veille.decide(_day_state("twitch:AAA"), _make_config(tmp_path))
    assert "aucune préférence déclarée" in fake.calls[0].prompt
    assert state["llm"]["status"] == "ok" and state["proposals"] == []


@pytest.mark.parametrize("answer", [
    _picks("twitch:ZZZ"),                       # id inconnu
    _picks("twitch:AAA", "twitch:AAA"),         # doublon
    _picks("twitch:AAA", "twitch:BBB"),         # plus que max_vods_per_day
    {"picks": [{"candidate_id": "twitch:AAA", "reason": ""}], "skipped_note": ""},  # raison vide
    {"picks": [{"candidate_id": "twitch:AAA", "reason": "x" * 241}], "skipped_note": ""},
    {"picks": [], "skipped_note": "n" * 301},
])
def test_decide_refused_answer_is_an_error_with_no_replacement(tmp_path, answer):
    config = _make_config(tmp_path, max_vods_per_day=1)
    fake = FakeBackend([answer])
    with llm.use_backend(fake):
        state = veille.decide(_day_state("twitch:AAA", "twitch:BBB"), config)
    assert state["llm"]["status"] == "error" and state["llm"]["error"]
    assert state["proposals"] == []


def test_decide_with_no_candidate_skips_without_calling_claude(tmp_path):
    fake = FakeBackend([_picks()])
    with llm.use_backend(fake):
        state = veille.decide(_day_state(), _make_config(tmp_path))
    assert fake.calls == [] and state["llm"]["status"] == "skipped" and state["proposals"] == []


# --- run_if_due -------------------------------------------------------------


def _yt(video_id):
    """VOD à URL youtu.be : worker.enqueue ne lance alors aucun fil de miniature (pas de réseau)."""
    return {**_vod(video_id), "url": f"https://youtu.be/{video_id}"}


def _run_collectors():
    return _collectors(vods=[_yt("AAA"), _yt("BBB")])


def test_run_if_due_disabled_writes_nothing(tmp_path):
    config = _make_config(tmp_path, enabled=False)
    fake = FakeBackend([_picks()])
    with llm.use_backend(fake):
        assert veille.run_if_due(AFTER_RUN_AT, config, _run_collectors()) is None
    assert not _sdir(tmp_path).exists() and fake.calls == []


def test_run_if_due_before_run_at_does_nothing(tmp_path):
    config = _make_config(tmp_path, enabled=True)
    fake = FakeBackend([_picks()])
    with llm.use_backend(fake):
        assert veille.run_if_due(BEFORE_RUN_AT, config, _run_collectors()) is None
    assert not _sdir(tmp_path).exists() and fake.calls == []


def test_run_if_due_after_run_at_collects_decides_and_stamps_both_times(tmp_path):
    config = _make_config(tmp_path, enabled=True)
    fake = FakeBackend([_picks("twitch:AAA")])
    with llm.use_backend(fake):
        veille.run_if_due(AFTER_RUN_AT, config, _run_collectors())
    state = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    assert state["started_at"] and state["finished_at"] and state["finished_at"] >= state["started_at"]
    assert state["llm"]["status"] == "ok"
    assert [p["candidate_id"] for p in state["proposals"]] == ["twitch:AAA"]
    assert len(state["candidates"]) == 2


def test_run_if_due_started_at_is_written_before_the_collectors_run(tmp_path):
    config = _make_config(tmp_path, enabled=True)
    seen = {}

    def twitch(settings):
        seen["day"] = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
        return {"games": [], "vods": []}

    collectors = {**_run_collectors(), "twitch": twitch}
    with llm.use_backend(FakeBackend([_picks()])):
        veille.run_if_due(AFTER_RUN_AT, config, collectors)
    assert seen["day"]["started_at"] and seen["day"]["finished_at"] is None


def test_run_if_due_does_not_run_twice_the_same_day(tmp_path):
    config = _make_config(tmp_path, enabled=True)
    collectors = _run_collectors()
    with llm.use_backend(FakeBackend([_picks()])):
        veille.run_if_due(AFTER_RUN_AT, config, collectors)
        assert veille.run_if_due(AFTER_RUN_AT + timedelta(hours=1), config, collectors) is None
    assert collectors["steam"].calls == 1


def test_run_if_due_refresh_replays_the_day_and_keeps_decided_proposals(tmp_path):
    config = _make_config(tmp_path, enabled=True, max_vods_per_day=3)
    collectors = _run_collectors()
    with llm.use_backend(FakeBackend([_picks("twitch:AAA", "twitch:BBB")])):
        veille.run_if_due(AFTER_RUN_AT, config, collectors)
    veille.ignore(TODAY, "twitch:AAA", config)
    refresh = _sdir(tmp_path) / "refresh.json"
    refresh.write_text(json.dumps({"requested_at": AFTER_RUN_AT.isoformat()}), encoding="utf-8")
    collectors["twitch"].result = {"games": [{"name": "Jeu Alpha", "viewers_fr": 1000}],
                                   "vods": [_yt("AAA"), _yt("BBB"), _yt("CCC")]}
    fake = FakeBackend([_picks("twitch:BBB", "twitch:CCC")])
    with llm.use_backend(fake):
        veille.run_if_due(AFTER_RUN_AT + timedelta(minutes=5), config, collectors)
    assert not refresh.exists()
    assert collectors["steam"].calls == 2
    state = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    # AAA ignoré : plus candidat, conservé tel quel ; BBB et CCC remplacés par le nouveau choix
    assert [(p["candidate_id"], p["status"]) for p in state["proposals"]] == [
        ("twitch:AAA", "ignored"), ("twitch:BBB", "proposed"), ("twitch:CCC", "proposed")]
    assert "twitch:AAA" not in {c["id"] for c in state["candidates"]}


def test_run_if_due_refresh_works_even_before_run_at_and_with_an_existing_day(tmp_path):
    config = _make_config(tmp_path, enabled=True)
    (_sdir(tmp_path) / "days").mkdir(parents=True)
    (_sdir(tmp_path) / "refresh.json").write_text(json.dumps({"requested_at": "x"}), encoding="utf-8")
    with llm.use_backend(FakeBackend([_picks()])):
        assert veille.run_if_due(BEFORE_RUN_AT, config, _run_collectors()) is not None
    assert not (_sdir(tmp_path) / "refresh.json").exists()


# --- clip / ignore ------------------------------------------------------------


def _decided(tmp_path, **table):
    config = _make_config(tmp_path, enabled=True, **table)
    with llm.use_backend(FakeBackend([_picks("twitch:AAA", "twitch:BBB")])):
        veille.run_if_due(AFTER_RUN_AT, config, _run_collectors())
    return config


def test_clip_enqueues_the_vod_and_records_it(tmp_path):
    config = _decided(tmp_path)
    entry = veille.clip(TODAY, "twitch:AAA", "ma_chaine", short_clips=True, config=config)
    queue = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert len(queue) == 1 and queue[0]["id"] == entry["id"]
    assert queue[0]["url"] == "https://youtu.be/AAA"
    assert queue[0]["channel"] == "ma_chaine" and queue[0]["action"] == "run" and queue[0]["short_clips"] is True
    state = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    proposal = next(p for p in state["proposals"] if p["candidate_id"] == "twitch:AAA")
    assert proposal["status"] == "queued" and proposal["queue_entry_id"] == entry["id"]
    assert proposal["channel"] == "ma_chaine" and proposal["decided_at"]
    seen = _read(_sdir(tmp_path) / "seen.json")
    assert [(q["candidate_id"], q["video_id"], q["channel"], q["queue_entry_id"]) for q in seen["queued"]] == [
        ("twitch:AAA", entry["video_id"], "ma_chaine", entry["id"])]


def test_clip_twice_or_unknown_candidate_raises(tmp_path):
    config = _decided(tmp_path)
    veille.clip(TODAY, "twitch:AAA", None, config=config)
    with pytest.raises(veille.VeilleError, match="twitch:AAA"):
        veille.clip(TODAY, "twitch:AAA", None, config=config)
    with pytest.raises(veille.VeilleError, match="twitch:ZZZ"):
        veille.clip(TODAY, "twitch:ZZZ", None, config=config)
    with pytest.raises(veille.VeilleError):
        veille.ignore(TODAY, "twitch:AAA", config)


def test_ignore_marks_ignored_and_the_next_collect_drops_the_candidate(tmp_path):
    config = _decided(tmp_path)
    veille.ignore(TODAY, "twitch:BBB", config)
    state = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    assert next(p for p in state["proposals"] if p["candidate_id"] == "twitch:BBB")["status"] == "ignored"
    assert _read(_sdir(tmp_path) / "seen.json")["ignored"][0]["video_id"] == "BBB"
    again = veille.collect(NOW, collectors=_run_collectors(), config=config)
    assert "twitch:BBB" not in {c["id"] for c in again["candidates"]}
    with pytest.raises(veille.VeilleError):
        veille.ignore(TODAY, "twitch:BBB", config)


# --- select_best / restore ------------------------------------------------------


def _clip_files(tmp_path, video_id, clips):
    """clips : {clip_id: (score, qa_status, extra)} -> output/<video_id>/<clip_id>.json."""
    folder = tmp_path / "output" / video_id
    folder.mkdir(parents=True, exist_ok=True)
    for clip_id, (score, qa, extra) in clips.items():
        (folder / f"{clip_id}.json").write_text(json.dumps(
            {"video_id": video_id, "clip_id": clip_id, "score": score, "qa": {"status": qa, "issues": []}, **extra}),
            encoding="utf-8")
        (folder / f"{clip_id}.mp4").write_bytes(b"mp4-" + clip_id.encode())


def _done_video(tmp_path, video_id, *, finished="2026-10-06T10:00:00+00:00", status="done"):
    path = tmp_path / "workspace" / video_id / "pipeline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"video_id": video_id, "status": status, "updated_at": finished}), encoding="utf-8")


def _seen(tmp_path, *video_ids):
    path = _sdir(tmp_path) / "seen.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"queued": [
        {"candidate_id": f"twitch:{v}", "video_id": v, "url": f"https://youtu.be/{v}", "date": TODAY,
         "channel": None, "queue_entry_id": "e", "at": NOW.isoformat()} for v in video_ids], "ignored": []}),
        encoding="utf-8")


def _publish_entry(tmp_path, video_id, clip_id, status):
    path = tmp_path / "state" / "publish" / "ma_chaine.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    existing.append({"video_id": video_id, "clip_id": clip_id, "series_id": None, "part": None, "status": status,
                     "slot_at": None, "decided_at": None, "published_at": None, "error": None})
    path.write_text(json.dumps(existing), encoding="utf-8")


def _sel_config(tmp_path, **table):
    config = _make_config(tmp_path, **table)
    config._sections["publish"] = {"state_dir": str(tmp_path / "state" / "publish")}
    return config


def _tree(tmp_path):
    return {p.relative_to(tmp_path / "output"): (p.stat().st_mtime_ns, p.read_bytes())
            for p in sorted((tmp_path / "output").rglob("*")) if p.is_file()}


def test_select_best_keeps_the_best_scores_and_archives_the_rest(tmp_path):
    config = _sel_config(tmp_path, best_clips_per_day=3)
    _seen(tmp_path, "AAA", "BBB")
    _done_video(tmp_path, "AAA")
    _done_video(tmp_path, "BBB", finished="2026-10-06T12:00:00+00:00")
    _clip_files(tmp_path, "AAA", {"a1": (9.0, "passed", {}), "a2": (5.0, "passed", {}), "a3": (7.5, "passed", {}),
                                  "a4": (9.9, "rejected", {}),
                                  "s-p1": (6.0, "passed", {"part": 1, "parts_total": 2}),
                                  "s-p2": (6.0, "passed", {"part": 2, "parts_total": 2})})
    _clip_files(tmp_path, "BBB", {"b1": (8.0, "passed", {}), "b2": (1.0, "passed", {})})
    _clip_files(tmp_path, "OTHER", {"o1": (10.0, "passed", {})})  # vidéo hors veille
    before = _tree(tmp_path)
    veille.select_best(NOW + timedelta(hours=6), config)
    sel = _read(_sdir(tmp_path) / "selection" / f"{TODAY}.json")
    assert [(k["video_id"], k["clip_id"], k["rank"]) for k in sel["kept"]] == [
        ("AAA", "a1", 1), ("BBB", "b1", 2), ("AAA", "a3", 3)]
    archived = {(a["video_id"], a["clip_id"]) for a in sel["archived"]}
    assert archived == {("AAA", "a2"), ("AAA", "s-p1"), ("AAA", "s-p2"), ("BBB", "b2")}
    assert all(a["rank"] >= 4 for a in sel["archived"])
    assert ("AAA", "a4") not in archived and sel["restored"] == []
    assert not any(v == "OTHER" for v, _ in archived | {(k["video_id"], k["clip_id"]) for k in sel["kept"]})
    assert _tree(tmp_path) == before


def test_select_best_counts_a_series_as_one(tmp_path):
    config = _sel_config(tmp_path, best_clips_per_day=2)
    _seen(tmp_path, "AAA")
    _done_video(tmp_path, "AAA")
    _clip_files(tmp_path, "AAA", {"s-p1": (9.0, "passed", {"part": 1, "parts_total": 2}),
                                  "s-p2": (9.0, "passed", {"part": 2, "parts_total": 2}),
                                  "x": (8.0, "passed", {}), "y": (7.0, "passed", {})})
    veille.select_best(NOW + timedelta(hours=6), config)
    sel = _read(_sdir(tmp_path) / "selection" / f"{TODAY}.json")
    assert {k["clip_id"] for k in sel["kept"]} == {"s-p1", "s-p2", "x"}
    assert {a["clip_id"] for a in sel["archived"]} == {"y"}


@pytest.mark.parametrize("status", ["approved", "scheduled", "published"])
def test_select_best_never_archives_a_clip_in_the_publish_queue(tmp_path, status):
    config = _sel_config(tmp_path, best_clips_per_day=1)
    _seen(tmp_path, "AAA")
    _done_video(tmp_path, "AAA")
    _clip_files(tmp_path, "AAA", {"a1": (9.0, "passed", {}), "a2": (1.0, "passed", {})})
    _publish_entry(tmp_path, "AAA", "a2", status)
    veille.select_best(NOW + timedelta(hours=6), config)
    sel = _read(_sdir(tmp_path) / "selection" / f"{TODAY}.json")
    assert {k["clip_id"] for k in sel["kept"]} == {"a1", "a2"} and sel["archived"] == []


def test_select_best_ignores_unfinished_videos_and_groups_by_day(tmp_path):
    config = _sel_config(tmp_path, best_clips_per_day=1)
    _seen(tmp_path, "AAA", "BBB")
    _done_video(tmp_path, "AAA", status="running")
    _done_video(tmp_path, "BBB", finished="2026-10-05T10:00:00+00:00")
    _clip_files(tmp_path, "AAA", {"a1": (9.0, "passed", {})})
    _clip_files(tmp_path, "BBB", {"b1": (9.0, "passed", {}), "b2": (1.0, "passed", {})})
    veille.select_best(NOW + timedelta(hours=6), config)
    assert not (_sdir(tmp_path) / "selection" / f"{TODAY}.json").exists()
    sel = _read(_sdir(tmp_path) / "selection" / "2026-10-05.json")
    assert [k["clip_id"] for k in sel["kept"]] == ["b1"] and [a["clip_id"] for a in sel["archived"]] == ["b2"]


def test_restore_moves_an_archived_clip_to_restored_and_it_stays_after_recompute(tmp_path):
    config = _sel_config(tmp_path, best_clips_per_day=1)
    _seen(tmp_path, "AAA")
    _done_video(tmp_path, "AAA")
    _clip_files(tmp_path, "AAA", {"a1": (9.0, "passed", {}), "a2": (1.0, "passed", {})})
    veille.select_best(NOW, config)
    veille.restore("AAA", "a2", config)
    path = _sdir(tmp_path) / "selection" / f"{TODAY}.json"
    sel = _read(path)
    assert sel["archived"] == [] and [(r["video_id"], r["clip_id"]) for r in sel["restored"]] == [("AAA", "a2")]
    assert sel["restored"][0]["restored_at"]
    veille.select_best(NOW + timedelta(hours=1), config)
    sel = _read(path)
    assert sel["archived"] == [] and [r["clip_id"] for r in sel["restored"]] == ["a2"]
    with pytest.raises(veille.VeilleError):
        veille.restore("OTHER", "o1", config)
