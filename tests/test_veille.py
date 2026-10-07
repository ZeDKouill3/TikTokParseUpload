"""veille.py : relevé quotidien des sujets chauds (TASK-87cd, SPEC-bdd9 R1, R2, R4, R5).

Collecteurs injectés, ``tmp_path`` pour ``state/`` : aucun test ne touche le réseau.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from clipper import veille, veille_sources
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


@pytest.fixture(autouse=True)
def _no_real_access_check(monkeypatch):
    """Aucun test ne lance yt-dlp : le test d'accès par défaut est neutralisé (sauf test dédié)."""
    monkeypatch.setattr(veille_sources, "check_twitch_access", lambda url, timeout_s: None)


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
        "steam_fr": Collector({"games": []}),
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
        "steam_name_lookups_max": 100, "twitch_access_check_max": 30, "twitch_client_id": "", "twitch_client_secret": "", "youtube_api_key": "",
        "state_dir": "state/veille", "http_timeout_s": 20,
        "steam_rank_gain_min": 5, "steam_risers_max": 10, "steam_sellers_top": 50,
        "upcoming_days": 14, "release_window_days": 15, "igdb_min_hypes": 0, "igdb_releases_max": 30,
        "igdb_pages_max": 4,
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
    assert history["steam"] == {"42": {"name": "Jeu  Alpha !", "players": 5000, "rank": None, "last_week_rank": None}}
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


def _rank_collectors(**steam):
    collectors = _collectors()
    collectors["steam"] = Collector({"games": [{"appid": "42", "name": "Jeu Alpha", "players": 5000, **steam}]})
    return collectors


def _alpha(tmp_path, config, **steam):
    veille.collect(NOW, collectors=_rank_collectors(**steam), config=config)
    return _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")


def test_steam_rank_gain_is_an_immediate_signal_without_history(tmp_path, config):
    day = _alpha(tmp_path, config, rank=3, last_week_rank=10)
    game = day["games"][0]
    assert game["baseline_days_available"] == 0 and game["steam_delta_pct"] is None
    assert game["steam_rank"] == 3 and game["steam_rank_gain"] == 7 and game["steam_new_in_top"] is False
    saved = _read(_sdir(tmp_path) / "history" / f"{TODAY}.json")["steam"]["42"]
    assert saved["rank"] == 3 and saved["last_week_rank"] == 10


def test_steam_absent_last_week_means_new_in_top_not_a_number(tmp_path, config):
    game = _alpha(tmp_path, config, rank=5, last_week_rank=0)["games"][0]
    assert game["steam_new_in_top"] is True and game["steam_rank_gain"] is None


def test_steam_unknown_last_week_rank_is_null_not_invented(tmp_path, config):
    game = _alpha(tmp_path, config)["games"][0]
    assert game["steam_new_in_top"] is None and game["steam_rank_gain"] is None


def test_steam_rank_signal_reaches_candidates_and_claude(tmp_path, config):
    collectors = _rank_collectors(rank=3, last_week_rank=10)
    collectors["twitch"] = Collector({"games": [{"name": "Jeu Alpha", "viewers_fr": 10}], "vods": [_vod("v1")]})
    state = veille.collect(NOW, collectors=collectors, config=config)
    signals = state["candidates"][0]["signals"]
    assert signals["steam_rank_gain"] == 7 and signals["steam_new_in_top"] is False
    fake = FakeBackend([{"picks": [], "skipped_note": ""}])
    with llm.use_backend(fake):
        veille.decide(state, config)
    assert fake.calls[0].prompt.count("steam_rank_gain_vs_last_week=7") == 2
    assert "steam_new_in_top=False" in fake.calls[0].prompt


def _steam_only(tmp_path, config, games, twitch_error=True):
    """Relevé Twitch en erreur (ou sans jeu) et Steam ok."""
    collectors = _collectors()
    collectors["twitch"] = (Collector(error=RuntimeError("401")) if twitch_error
                            else Collector({"games": [{"name": "Jeu Alpha", "viewers_fr": 10}], "vods": []}))
    collectors["steam"] = Collector({"games": games})
    veille.collect(NOW, collectors=collectors, config=config)
    return _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")


def _sg(appid, name, rank, last, players=1000):
    return {"appid": appid, "name": name, "players": players, "rank": rank, "last_week_rank": last}


def test_steam_risers_listed_without_twitch(tmp_path, config):
    day = _steam_only(tmp_path, config, [
        _sg("1", "Jeu Nouveau", 5, -1), _sg("2", "Jeu Bond", 10, 20), _sg("3", "Jeu Stable", 3, 4),
        _sg("4", "Jeu Inconnu", 7, None), _sg("5", "Jeu Seuil", 8, 13),
    ])
    assert day["sources"]["twitch"]["status"] == "error"
    by_name = {g["name"]: g for g in day["games"]}
    assert set(by_name) == {"Jeu Nouveau", "Jeu Bond", "Jeu Seuil"}
    new = by_name["Jeu Nouveau"]
    assert new["source"] == "steam" and new["twitch_match"] is False and new["steam_match"] is True
    assert new["twitch_fr_viewers"] is None and new["twitch_delta_pct"] is None
    assert new["steam_rank"] == 5 and new["steam_new_in_top"] is True and new["steam_rank_gain"] is None
    assert new["steam_appid"] == "1" and new["steam_players"] == 1000 and new["vod_count"] == 0
    assert by_name["Jeu Bond"]["steam_rank_gain"] == 10 and by_name["Jeu Bond"]["steam_new_in_top"] is False
    assert by_name["Jeu Seuil"]["steam_rank_gain"] == 5


def test_steam_risers_gain_threshold_and_cap_are_settings(tmp_path):
    games = [_sg(str(i), f"Jeu {i}", i, i + 3) for i in range(1, 4)] + [_sg("9", "Jeu Neuf", 50, 0)]
    day = _steam_only(tmp_path, _make_config(tmp_path, steam_rank_gain_min=3, steam_risers_max=2), games)
    assert len(day["games"]) == 2
    assert day["games"][0]["name"] == "Jeu Neuf"  # nouveau dans le top d'abord


def test_steam_riser_already_on_twitch_is_not_duplicated(tmp_path, config):
    day = _steam_only(tmp_path, config, [_sg("42", "Jeu Alpha", 5, 0)], twitch_error=False)
    assert [g["key"] for g in day["games"]] == ["jeu alpha"]
    assert day["games"][0]["twitch_match"] is True and day["games"][0]["source"] == "twitch"


def test_steam_risers_reach_claude_context(tmp_path, config):
    day = _steam_only(tmp_path, config, [_sg("1", "Jeu Nouveau", 5, -1)])
    fake = FakeBackend([{"picks": [], "skipped_note": ""}])
    day["candidates"] = [{"id": "c1", "source": "twitch", "title": "t", "channel_name": "c", "duration_s": 3600,
                          "published_at": NOW.isoformat()}]
    with llm.use_backend(fake):
        veille.decide(day, config)
    assert "- Jeu Nouveau : twitch_fr_viewers=inconnu" in fake.calls[0].prompt
    assert "steam_new_in_top=True" in fake.calls[0].prompt


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


# --- TASK-2784 : top des ventes Steam du pays ----------------------------------


def _sellers_collectors(sellers, **twitch):
    collectors = _collectors()
    collectors["steam_fr"] = Collector({"games": sellers})
    if twitch:
        collectors["twitch"] = Collector(twitch)
    return collectors


def _seller(appid, name, rank, last):
    return {"appid": appid, "name": name, "rank": rank, "last_week_rank": last}


def test_sellers_merge_by_normalized_key_into_twitch_game_without_duplicate(tmp_path, config):
    state = veille.collect(NOW, collectors=_sellers_collectors([_seller("9", "JEU alpha", 4, 14)]), config=config)
    assert [g["key"] for g in state["games"]] == ["jeu alpha"]
    game = state["games"][0]
    assert game["steam_sellers_rank"] == 4 and game["steam_sellers_last_week_rank"] == 14
    assert game["steam_sellers_gain"] == 10 and game["steam_sellers_new"] is False
    assert state["sources"]["steam_fr"]["status"] == "ok" and state["sources"]["steam_fr"]["counts"] == {"games": 1}


def test_sellers_game_without_sellers_entry_has_null_fields(tmp_path, config):
    game = veille.collect(NOW, collectors=_collectors(), config=config)["games"][0]
    assert game["steam_sellers_rank"] is None and game["steam_sellers_gain"] is None and game["steam_sellers_new"] is None


def test_sellers_new_in_top_has_no_numeric_gain(tmp_path, config):
    game = veille.collect(NOW, collectors=_sellers_collectors([_seller("9", "Jeu Alpha", 4, 0)]), config=config)["games"][0]
    assert game["steam_sellers_new"] is True and game["steam_sellers_gain"] is None


def test_sellers_risers_are_added_without_twitch_and_small_gain_is_not(tmp_path, config):
    sellers = [_seller("1", "Montant", 8, 17), _seller("2", "Nouveau", 3, 0), _seller("3", "Stable", 1, 3),
               _seller("4", "Recule", 5, 2)]
    state = veille.collect(NOW, collectors=_sellers_collectors(sellers), config=config)
    added = {g["name"]: g for g in state["games"] if g["source"] == "steam_fr"}
    assert set(added) == {"Montant", "Nouveau"}
    assert added["Montant"]["twitch_match"] is False and added["Montant"]["twitch_fr_viewers"] is None
    assert added["Montant"]["steam_sellers_gain"] == 9 and added["Nouveau"]["steam_sellers_new"] is True
    assert added["Montant"]["steam_match"] is False and added["Montant"]["steam_players"] is None


def test_sellers_riser_already_a_world_steam_riser_is_not_duplicated(tmp_path, config):
    collectors = _collectors()
    collectors["steam"] = Collector({"games": [{"appid": "7", "name": "Montant", "players": 10, "rank": 2, "last_week_rank": 30}]})
    collectors["steam_fr"] = Collector({"games": [_seller("7", "Montant", 8, 17)]})
    games = veille.collect(NOW, collectors=collectors, config=config)["games"]
    assert [g["name"] for g in games].count("Montant") == 1
    montant = next(g for g in games if g["name"] == "Montant")
    assert montant["steam_rank_gain"] == 28 and montant["steam_sellers_gain"] == 9


def test_sellers_risers_are_capped_by_steam_risers_max(tmp_path):
    config = _make_config(tmp_path, steam_risers_max=1)
    sellers = [_seller("1", "A", 3, 0), _seller("2", "B", 4, 0)]
    games = veille.collect(NOW, collectors=_sellers_collectors(sellers), config=config)["games"]
    assert [g["name"] for g in games if g["source"] == "steam_fr"] == ["A"]


def test_sellers_error_is_named_and_other_sources_continue(tmp_path, config):
    collectors = _collectors()
    collectors["steam_fr"] = Collector(error=veille.veille_sources.SourceError("HTTP 500 boom"))
    state = veille.collect(NOW, collectors=collectors, config=config)
    assert state["sources"]["steam_fr"]["status"] == "error" and "HTTP 500 boom" in state["sources"]["steam_fr"]["error"]
    assert state["sources"]["steam"]["status"] == "ok" and state["sources"]["twitch"]["status"] == "ok"
    assert state["games"][0]["steam_sellers_rank"] is None


def test_sellers_saved_in_history_and_signals_reach_candidates_and_claude(tmp_path, config):
    collectors = _sellers_collectors([_seller("9", "Jeu Alpha", 4, 14)],
                                     games=[{"name": "Jeu Alpha", "viewers_fr": 10}], vods=[_vod("v1")])
    state = veille.collect(NOW, collectors=collectors, config=config)
    assert _read(_sdir(tmp_path) / "history" / f"{TODAY}.json")["steam_fr"]["9"] == {
        "name": "Jeu Alpha", "rank": 4, "last_week_rank": 14}
    signals = state["candidates"][0]["signals"]
    assert signals["steam_sellers_gain"] == 10 and signals["steam_sellers_new"] is False
    fake = FakeBackend([{"picks": [], "skipped_note": ""}])
    with llm.use_backend(fake):
        veille.decide(state, config)
    prompt = fake.calls[0].prompt
    assert prompt.count("ventes_fr_rang=4") == 1 and prompt.count("ventes_fr_gain_vs_semaine_derniere=10") == 2


def test_sellers_settings_defaults():
    assert veille.CONFIG_DEFAULTS["steam_sellers_top"] == 50


# --- TASK-a898 : compteur de VOD réservées, miniature conservée -------------


def test_private_vod_count_is_shown_in_the_twitch_source_detail(tmp_path, config):
    collectors = _collectors(vods=[_vod("ok1")])
    collectors["twitch"].result["private_vods"] = 3
    veille.collect(NOW, collectors=collectors, config=config)
    day = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    assert day["sources"]["twitch"]["counts"] == {"games": 1, "vods": 1, "private": 3, "restricted": 0}


def test_candidate_carries_the_thumbnail_url_or_none(tmp_path, config):
    with_thumb = {**_vod("t1"), "thumbnail_url": "https://cdn.test/t1.jpg"}
    veille.collect(NOW, collectors=_collectors(vods=[with_thumb, _vod("t2")]), config=config)
    day = _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")
    assert {c["video_id"]: c["thumbnail_url"] for c in day["candidates"]} == {"t1": "https://cdn.test/t1.jpg", "t2": None}


# --- TASK-9495 : test d'accès des VOD Twitch avant de les proposer ------------


class FakeAccess:
    """Test d'accès factice : ``outcomes[video_id]`` = exception à lever (absent = accessible)."""

    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.urls = []

    def __call__(self, url, timeout_s):
        self.urls.append(url)
        outcome = self.outcomes.get(url.rsplit("/", 1)[-1])
        if outcome is not None:
            raise outcome


def _day(tmp_path):
    return _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")


def test_access_check_max_default_is_30():
    assert veille.CONFIG_DEFAULTS["twitch_access_check_max"] == 30


def test_subscriber_only_vod_is_dropped_and_counted(tmp_path, config):
    err = veille_sources.AccessRestricted("You must be logged into an account that has access to this subscriber-only content")
    access = FakeAccess({"sub": err})
    veille.collect(NOW, collectors=_collectors(vods=[_vod("ok"), _vod("sub")]), config=config, access_check=access)
    day = _day(tmp_path)
    assert [c["video_id"] for c in day["candidates"]] == ["ok"]
    assert day["sources"]["twitch"]["counts"]["restricted"] == 1
    assert day["sources"]["twitch"]["counts"]["private"] == 0


def test_accessible_vod_is_kept_without_unverified_mark(tmp_path, config):
    veille.collect(NOW, collectors=_collectors(vods=[_vod("ok")]), config=config, access_check=FakeAccess())
    cand = _day(tmp_path)["candidates"][0]
    assert cand["access_unverified"] is None
    assert _day(tmp_path)["sources"]["twitch"]["counts"]["restricted"] == 0


def test_other_error_keeps_candidate_marked_unverified_with_reason(tmp_path, config):
    access = FakeAccess({"net": ConnectionResetError("WinError 10054 connexion fermée")})
    veille.collect(NOW, collectors=_collectors(vods=[_vod("net")]), config=config, access_check=access)
    day = _day(tmp_path)
    assert [c["video_id"] for c in day["candidates"]] == ["net"]
    assert "WinError 10054" in day["candidates"][0]["access_unverified"]
    assert day["sources"]["twitch"]["counts"]["restricted"] == 0


def test_cap_checks_most_viewed_first_and_marks_the_rest_unverified(tmp_path):
    config = _make_config(tmp_path, twitch_access_check_max=2)
    vods = [{**_vod(f"v{i}"), "view_count": views} for i, views in enumerate([10, 500, 300, 5])]
    access = FakeAccess()
    veille.collect(NOW, collectors=_collectors(vods=vods), config=config, access_check=access)
    assert sorted(u.rsplit("/", 1)[-1] for u in access.urls) == ["v1", "v2"]
    marks = {c["video_id"]: c["access_unverified"] for c in _day(tmp_path)["candidates"]}
    assert marks["v1"] is None and marks["v2"] is None
    assert marks["v0"] and marks["v3"]  # raison non vide : au-delà du plafond


def test_filtered_out_vods_are_not_tested(tmp_path, config):
    access = FakeAccess()
    veille.collect(NOW, collectors=_collectors(vods=[_vod("short", duration_s=60), _vod("ok")]), config=config, access_check=access)
    assert [u.rsplit("/", 1)[-1] for u in access.urls] == ["ok"]


def test_no_access_call_when_twitch_source_is_in_error(tmp_path, config):
    collectors = _collectors(vods=[_vod("ok")])
    collectors["twitch"] = Collector(error=RuntimeError("helix down"))
    access = FakeAccess()
    veille.collect(NOW, collectors=collectors, config=config, access_check=access)
    assert access.urls == []


def test_youtube_candidates_are_not_access_tested(tmp_path, config):
    access = FakeAccess()
    veille.collect(NOW, collectors=_collectors(videos=[_vod("yt1", source="youtube")]), config=config, access_check=access)
    assert access.urls == []
    assert _day(tmp_path)["candidates"][0]["access_unverified"] is None


def test_default_access_check_goes_through_veille_sources(tmp_path, config, monkeypatch):
    seen = []
    monkeypatch.setattr(veille_sources, "check_twitch_access", lambda url, timeout_s: seen.append((url, timeout_s)))
    veille.collect(NOW, collectors=_collectors(vods=[_vod("ok")]), config=config)
    assert seen == [("https://example.test/ok", 20)]


# ==========================================================================
# TASK-9d01 : source IGDB, sorties du jour, repère J+N, prompt (SPEC-4efa R11 à R16)
# ==========================================================================

EMPTY_RELEASES = {"recent": [], "upcoming": [], "excluded_low_hypes": 0, "truncated": {"recent": 0, "upcoming": 0}}


def _rel(igdb_id, name, date, *, hypes=10, platform="PC", region="Worldwide", status="Released"):
    return {"igdb_id": str(igdb_id), "name": name, "slug": name.lower().replace(" ", "-"),
            "url": f"https://igdb.test/{igdb_id}", "first_release_date": None, "date": date, "hypes": hypes,
            "human": date, "platform": platform, "region": region, "status": status, "date_format": "YYYY-MM-DD"}


def _with_igdb(releases, *, skipped=0, **kwargs):
    collectors = _collectors(**kwargs)
    collectors["igdb"] = Collector({"releases": list(releases), "skipped_rows": skipped})
    return collectors


def _day(tmp_path):
    return _read(_sdir(tmp_path) / "days" / f"{TODAY}.json")


@pytest.mark.parametrize("key, bad", [
    ("upcoming_days", 0), ("release_window_days", -1), ("igdb_min_hypes", -1),
    ("igdb_releases_max", 0), ("igdb_pages_max", 0), ("upcoming_days", True), ("igdb_pages_max", "4"),
])
def test_igdb_settings_out_of_bounds_raise_naming_the_key(tmp_path, key, bad):
    config = _make_config(tmp_path, **{key: bad})
    with pytest.raises(veille.VeilleError, match=key):
        veille.collect(NOW, collectors=_collectors(), config=config)


def test_release_window_zero_is_valid(tmp_path):
    state = veille.collect(NOW, collectors=_with_igdb([_rel(1, "Pile Aujourdhui", TODAY)]),
                           config=_make_config(tmp_path, release_window_days=0))
    assert [r["name"] for r in state["releases"]["recent"]] == ["Pile Aujourdhui"]


@pytest.mark.parametrize("empty_key", ["twitch_client_id", "twitch_client_secret"])
def test_igdb_missing_twitch_keys_is_error_and_collector_not_called(tmp_path, empty_key):
    config = _make_config(tmp_path, **{empty_key: ""})
    collectors = _with_igdb([_rel(1, "Hytale", TODAY)])
    state = veille.collect(NOW, collectors=collectors, config=config)
    assert state["sources"]["igdb"]["status"] == "error"
    assert state["sources"]["igdb"]["error"] == f"{empty_key} absente : à saisir dans Réglages › Veille"
    assert collectors["igdb"].calls == 0
    assert state["releases"] == EMPTY_RELEASES


def test_failing_igdb_leaves_empty_releases_no_marker_other_sources_and_history_intact(tmp_path):
    ok_dir, ko_dir = tmp_path / "ok", tmp_path / "ko"
    vods = [_vod("v1")]
    veille.collect(NOW, collectors=_with_igdb([_rel(1, "Jeu Alpha", TODAY)], vods=vods), config=_make_config(ok_dir))
    broken = _collectors(vods=vods)
    broken["igdb"] = Collector(error=veille_sources.SourceError("HTTP 500 igdb boom"))
    state = veille.collect(NOW, collectors=broken, config=_make_config(ko_dir))
    assert state["sources"]["igdb"]["status"] == "error" and "igdb boom" in state["sources"]["igdb"]["error"]
    assert state["releases"] == EMPTY_RELEASES
    assert all(g["release"] is None for g in state["games"])
    assert all(c["signals"]["release_days_since"] is None for c in state["candidates"])
    assert all(state["sources"][s]["status"] == "ok" for s in ("twitch", "youtube", "steam", "steam_fr"))
    history = lambda base: _read(base / "state" / "veille" / "history" / f"{TODAY}.json")  # noqa: E731
    assert history(ko_dir) == history(ok_dir)


def test_igdb_groups_by_igdb_id_with_earliest_date_and_unique_sorted_lists(tmp_path):
    rows = [
        _rel(1, "Hytale", "2026-10-04", platform="PS5", region="Europe", status="Released"),
        _rel(1, "Hytale", "2026-10-02", platform="PC", region="Worldwide", status="Early Access"),
        _rel(1, "Hytale", "2026-10-04", platform="PC", region="Europe", status="Released"),
    ]
    state = veille.collect(NOW, collectors=_with_igdb(rows), config=_make_config(tmp_path))
    (entry,) = state["releases"]["recent"]
    assert entry == {"igdb_id": "1", "name": "Hytale", "key": "hytale", "slug": "hytale", "url": "https://igdb.test/1",
                     "hypes": 10, "date": "2026-10-02", "human": "2026-10-02", "platforms": ["PC", "PS5"],
                     "regions": ["Europe", "Worldwide"], "statuses": ["Early Access", "Released"], "days": -4}
    assert state["releases"]["upcoming"] == []


def test_igdb_window_bounds_recent_and_upcoming(tmp_path):
    rows = [_rel(1, "Moins16", "2026-09-20"), _rel(2, "Moins15", "2026-09-21"), _rel(3, "Zero", "2026-10-06"),
            _rel(4, "Plus1", "2026-10-07"), _rel(5, "Plus14", "2026-10-20"), _rel(6, "Plus15", "2026-10-21")]
    state = veille.collect(NOW, collectors=_with_igdb(rows), config=_make_config(tmp_path))
    releases = state["releases"]
    assert sorted(r["name"] for r in releases["recent"]) == ["Moins15", "Zero"]
    assert sorted(r["name"] for r in releases["upcoming"]) == ["Plus1", "Plus14"]
    assert [r["days"] for r in releases["upcoming"]] == [1, 14]


def test_igdb_sort_orders(tmp_path):
    rows = [
        _rel(1, "Vieux", "2026-10-01", hypes=500), _rel(2, "RecentBas", "2026-10-05", hypes=1),
        _rel(3, "RecentHaut", "2026-10-05", hypes=50), _rel(4, "RecentNull", "2026-10-05", hypes=None),
        _rel(5, "RecentB", "2026-10-05", hypes=None),
        _rel(6, "TardHaut", "2026-10-12", hypes=90), _rel(7, "TotBas", "2026-10-08", hypes=1),
        _rel(8, "TotHaut", "2026-10-08", hypes=9), _rel(9, "TotNull", "2026-10-08", hypes=None),
    ]
    state = veille.collect(NOW, collectors=_with_igdb(rows), config=_make_config(tmp_path))
    # recent : days décroissant, puis hypes décroissant (null en dernier), puis nom
    assert [r["name"] for r in state["releases"]["recent"]] == [
        "RecentHaut", "RecentBas", "RecentB", "RecentNull", "Vieux"]
    # upcoming : date croissante, puis hypes décroissant (null en dernier), puis nom
    assert [r["name"] for r in state["releases"]["upcoming"]] == ["TotHaut", "TotBas", "TotNull", "TardHaut"]


def test_igdb_min_hypes_drops_low_and_missing_and_counts(tmp_path):
    rows = [_rel(1, "Gros", "2026-10-05", hypes=100), _rel(2, "Petit", "2026-10-05", hypes=3),
            _rel(3, "Inconnu", "2026-10-05", hypes=None), _rel(4, "AVenirPetit", "2026-10-08", hypes=1),
            _rel(5, "AVenirGros", "2026-10-08", hypes=5)]
    state = veille.collect(NOW, collectors=_with_igdb(rows), config=_make_config(tmp_path, igdb_min_hypes=5))
    assert [r["name"] for r in state["releases"]["recent"]] == ["Gros"]
    assert [r["name"] for r in state["releases"]["upcoming"]] == ["AVenirGros"]
    assert state["releases"]["excluded_low_hypes"] == 3


def test_igdb_min_hypes_zero_keeps_unknown_hypes(tmp_path):
    state = veille.collect(NOW, collectors=_with_igdb([_rel(1, "Inconnu", "2026-10-05", hypes=None)]),
                           config=_make_config(tmp_path))
    assert [r["name"] for r in state["releases"]["recent"]] == ["Inconnu"]
    assert state["releases"]["excluded_low_hypes"] == 0


def test_igdb_lists_truncated_to_max_with_counts_and_source_counts(tmp_path):
    recent = [_rel(i, f"R{i}", "2026-10-05", hypes=100 - i) for i in range(1, 6)]
    upcoming = [_rel(10 + i, f"U{i}", "2026-10-08", hypes=100 - i) for i in range(1, 4)]
    state = veille.collect(NOW, collectors=_with_igdb(recent + upcoming, skipped=2),
                           config=_make_config(tmp_path, igdb_releases_max=2))
    assert [r["name"] for r in state["releases"]["recent"]] == ["R1", "R2"]
    assert [r["name"] for r in state["releases"]["upcoming"]] == ["U1", "U2"]
    assert state["releases"]["truncated"] == {"recent": 3, "upcoming": 1}
    counts = state["sources"]["igdb"]["counts"]
    assert counts == {"rows": 8, "recent": 2, "upcoming": 2, "skipped_rows": 2}
    assert state["sources"]["igdb"]["status"] == "ok" and state["sources"]["igdb"]["error"] is None
    assert _day(tmp_path)["releases"] == state["releases"]  # écrit dans days/<date>.json


def _games_collectors(*, twitch_games, releases, vods=()):
    collectors = _with_igdb(releases, vods=vods)
    collectors["twitch"] = Collector({"games": twitch_games, "vods": list(vods)})
    return collectors


def test_game_release_marker_matches_by_igdb_id_first_then_by_key_only_for_recent(tmp_path):
    games = [
        {"name": "Nom Twitch Different", "viewers_fr": 900, "igdb_id": "42"},   # par igdb_id (noms différents)
        {"name": "Hytale", "viewers_fr": 800, "igdb_id": ""},                   # par clé normalisée
        {"name": "Jeu Alpha", "viewers_fr": 700, "igdb_id": "7"},               # l'id gagne sur la clé
        {"name": "A Venir", "viewers_fr": 600, "igdb_id": "9"},                 # sortie à venir : pas de repère
        {"name": "Sans Sortie", "viewers_fr": 500},                             # champ igdb_id absent, aucune sortie
    ]
    releases = [_rel(42, "Autre Nom IGDB", "2026-10-03", hypes=33), _rel(5, "Hytale", "2026-10-05", hypes=77),
                _rel(7, "Pas Alpha", "2026-10-06", hypes=None), _rel(6, "Jeu Alpha", "2026-09-30"),
                _rel(9, "A Venir", "2026-10-09")]
    state = veille.collect(NOW, collectors=_games_collectors(twitch_games=games, releases=releases),
                           config=_make_config(tmp_path))
    by_name = {g["name"]: g for g in state["games"]}
    assert by_name["Nom Twitch Different"]["release"] == {
        "igdb_id": "42", "name": "Autre Nom IGDB", "date": "2026-10-03", "days_since": 3, "hypes": 33}
    assert by_name["Hytale"]["release"] == {
        "igdb_id": "5", "name": "Hytale", "date": "2026-10-05", "days_since": 1, "hypes": 77}
    assert by_name["Jeu Alpha"]["release"] == {
        "igdb_id": "7", "name": "Pas Alpha", "date": "2026-10-06", "days_since": 0, "hypes": None}
    assert by_name["A Venir"]["release"] is None
    assert by_name["Sans Sortie"]["release"] is None


def test_candidates_copy_release_days_since_from_their_game(tmp_path):
    games = [{"name": "Hytale", "viewers_fr": 800, "igdb_id": "5"}, {"name": "Jeu Alpha", "viewers_fr": 700, "igdb_id": ""}]
    vods = [_vod("h1", game="Hytale"), _vod("a1", game="Jeu Alpha"), _vod("o1", game="Orphelin")]
    state = veille.collect(NOW, collectors=_games_collectors(
        twitch_games=games, vods=vods, releases=[_rel(5, "Hytale", "2026-10-03")]), config=_make_config(tmp_path))
    days = {c["video_id"]: c["signals"]["release_days_since"] for c in state["candidates"]}
    assert days == {"h1": 3, "a1": None, "o1": None}


def _prompt_state(*, releases=None, igdb=None, game_release=None, days_since=None):
    state = _day_state("twitch:AAA")
    state["games"][0].update(release=game_release, steam_players=None)
    state["candidates"][0]["signals"]["release_days_since"] = days_since
    state["releases"] = releases if releases is not None else EMPTY_RELEASES
    state["sources"] = {"igdb": igdb or {"status": "ok", "error": None, "counts": {}}}
    return state


def _decide_prompt(tmp_path, state, **table):
    fake = FakeBackend([_picks()])
    with llm.use_backend(fake):
        veille.decide(state, _make_config(tmp_path, **table))
    assert len(fake.calls) == 1  # un seul appel, comme avant
    return fake.calls[0].prompt


def test_prompt_carries_release_markers_on_game_and_candidate_lines(tmp_path):
    state = _prompt_state(game_release={"igdb_id": "5", "name": "Jeu Alpha", "date": "2026-10-03", "days_since": 3,
                                        "hypes": 77}, days_since=3)
    prompt = _decide_prompt(tmp_path, state)
    game_line = next(line for line in prompt.splitlines() if line.startswith("- Jeu Alpha :"))
    assert "sortie_j_plus=3" in game_line and "hypes_igdb=77" in game_line
    candidate_line = next(line for line in prompt.splitlines() if line.startswith("- id=twitch:AAA"))
    assert "sortie_j_plus=3" in candidate_line


def test_prompt_marks_unknown_release_as_inconnu(tmp_path):
    prompt = _decide_prompt(tmp_path, _prompt_state())
    game_line = next(line for line in prompt.splitlines() if line.startswith("- Jeu Alpha :"))
    assert "sortie_j_plus=inconnu" in game_line and "hypes_igdb=inconnu" in game_line
    candidate_line = next(line for line in prompt.splitlines() if line.startswith("- id=twitch:AAA"))
    assert "sortie_j_plus=inconnu" in candidate_line


def test_prompt_has_release_block_and_priority_instruction(tmp_path):
    releases = {"recent": [{"igdb_id": "5", "name": "Hytale", "days": -3, "hypes": 77, "date": "2026-10-03",
                            "platforms": ["PC", "PS5"]}],
                "upcoming": [{"igdb_id": "6", "name": "Gros Jeu", "days": 4, "hypes": None, "date": "2026-10-10",
                              "platforms": ["Xbox"]}],
                "excluded_low_hypes": 0, "truncated": {"recent": 0, "upcoming": 0}}
    prompt = _decide_prompt(tmp_path, _prompt_state(releases=releases), release_window_days=12)
    assert "Sorties de jeux (IGDB)" in prompt
    assert "Hytale" in prompt and "J+3" in prompt and "77" in prompt and "PC, PS5" in prompt
    assert "Gros Jeu" in prompt and "2026-10-10" in prompt and "J-4" in prompt and "Xbox" in prompt
    assert ("Un jeu sorti depuis 0 à 12 jours est dans sa fenêtre de sortie : à qualité de gameplay égale, "
            "propose d'abord ses VOD ; une sortie à venir n'est pas un motif de choix aujourd'hui.") in prompt


def test_prompt_says_releases_unavailable_with_the_error(tmp_path):
    igdb = {"status": "error", "error": "HTTP 500 igdb boom", "counts": {}}
    prompt = _decide_prompt(tmp_path, _prompt_state(igdb=igdb))
    assert "Sorties de jeux : indisponibles (HTTP 500 igdb boom)" in prompt
    assert "Sorties de jeux (IGDB)" not in prompt


def test_decide_schema_check_and_call_count_unchanged_with_releases(tmp_path):
    fake = FakeBackend([_picks("twitch:AAA")])
    with llm.use_backend(fake):
        state = veille.decide(_prompt_state(), _make_config(tmp_path))
    assert len(fake.calls) == 1 and fake.calls[0].usage == "veille" and fake.calls[0].images == []
    assert [p["candidate_id"] for p in state["proposals"]] == ["twitch:AAA"]
