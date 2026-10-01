"""watch.py : surveillance des VOD d'une chaine (TASK-7508, SPEC-fc0c §5).

Le listeur est toujours injecte : aucun test n'appelle yt-dlp ni le reseau.
Seul ``test_real_lister_*`` (CLIPPER_REAL_NETWORK=1) touche un vrai service.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from clipper import watch
from clipper.config import Config

NOW = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
SOURCE_URL = "https://example.test/ma_chaine/videos"


def _vod(video_id: str, duration_s: int | None = 7200, **extra) -> dict:
    return {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "title": f"Direct {video_id}",
        "duration_s": duration_s,
        "published_at": "2026-01-01T20:00:00+00:00",
        **extra,
    }


VOD_A = "AAAAAAAAAAA"
VOD_B = "BBBBBBBBBBB"
VOD_C = "CCCCCCCCCCC"


class FakeLister:
    def __init__(self, vods=None, error: Exception | None = None):
        self.vods = vods or []
        self.error = error
        self.calls: list[str] = []

    def __call__(self, source_url: str) -> list[dict]:
        self.calls.append(source_url)
        if self.error is not None:
            raise self.error
        return list(self.vods)


@pytest.fixture
def env(tmp_path):
    """Presets + config.toml + config de test dans tmp_path ; un preset par chaine."""
    presets = tmp_path / "presets"
    presets.mkdir()
    base = tmp_path / "config.toml"
    base.write_text('mode = "review"\n', encoding="utf-8")

    config = Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={
            "worker": {"queue_path": str(tmp_path / "state" / "queue.json")},
            "watch": {
                "state_dir": str(tmp_path / "state" / "watch"),
                "presets_dir": str(presets),
                "base_config": str(base),
            },
        },
    )

    def channel(name: str, *, mode: str = "review", min_duration: int = 600, source_url: str = SOURCE_URL, watch_on=True):
        (presets / f"{name}.toml").write_text(
            f'[channel]\nsource_url = "{source_url}"\nwatch = {str(watch_on).lower()}\n'
            f'watch_min_duration_s = {min_duration}\nmode = "{mode}"\n',
            encoding="utf-8",
        )

    return config, channel, tmp_path


def _state(tmp_path, name: str = "ma_chaine") -> dict:
    return json.loads((tmp_path / "state" / "watch" / f"{name}.json").read_text(encoding="utf-8"))


def _queue(tmp_path) -> list[dict]:
    path = tmp_path / "state" / "queue.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _write_state(tmp_path, data: dict, name: str = "ma_chaine") -> None:
    path = tmp_path / "state" / "watch" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# --------------------------------------------------------------------------
# (1) check : listage, filtre de duree, seen, checked_at
# --------------------------------------------------------------------------


def test_check_lists_source_url_and_writes_checked_at(env):
    config, channel, tmp_path = env
    channel("ma_chaine")
    lister = FakeLister([])

    watch.check("ma_chaine", NOW, lister=lister, config=config)

    assert lister.calls == [SOURCE_URL]
    state = _state(tmp_path)
    assert state["checked_at"] == NOW.isoformat()
    assert state["seen"] == [] and state["pending"] == [] and state["last_error"] is None


def test_check_ignores_short_vods_and_seen_ones(env):
    config, channel, tmp_path = env
    channel("ma_chaine", min_duration=600)
    _write_state(tmp_path, {"checked_at": None, "seen": [VOD_A], "pending": [], "last_error": None})
    lister = FakeLister([_vod(VOD_A), _vod(VOD_B, duration_s=599), _vod(VOD_C, duration_s=600)])

    watch.check("ma_chaine", NOW, lister=lister, config=config)

    state = _state(tmp_path)
    assert [v["video_id"] for v in state["pending"]] == [VOD_C]
    assert state["seen"] == [VOD_A]  # la VOD courte n'est pas "vue" : elle est juste ignoree


def test_check_does_not_re_add_a_vod_already_pending(env):
    config, channel, tmp_path = env
    channel("ma_chaine")
    lister = FakeLister([_vod(VOD_A)])

    watch.check("ma_chaine", NOW, lister=lister, config=config)
    watch.check("ma_chaine", NOW + timedelta(hours=1), lister=lister, config=config)

    assert [v["video_id"] for v in _state(tmp_path)["pending"]] == [VOD_A]


def test_check_pending_entry_carries_the_contract_fields(env):
    config, channel, tmp_path = env
    channel("ma_chaine")

    watch.check("ma_chaine", NOW, lister=FakeLister([_vod(VOD_A)]), config=config)

    assert _state(tmp_path)["pending"] == [{
        "video_id": VOD_A, "url": f"https://youtu.be/{VOD_A}", "title": f"Direct {VOD_A}",
        "duration_s": 7200, "published_at": "2026-01-01T20:00:00+00:00", "found_at": NOW.isoformat(),
    }]


def test_check_vod_without_duration_is_reconsidered_later_not_marked_seen(env):
    config, channel, tmp_path = env
    channel("ma_chaine", mode="auto")

    watch.check("ma_chaine", NOW, lister=FakeLister([_vod(VOD_A, duration_s=None)]), config=config)

    state = _state(tmp_path)
    assert state["seen"] == [] and state["pending"] == []
    assert _queue(tmp_path) == []


# --------------------------------------------------------------------------
# (2) mode auto : file + seen ; mode review : pending
# --------------------------------------------------------------------------


def test_check_auto_mode_enqueues_each_new_vod_and_marks_it_seen(env):
    config, channel, tmp_path = env
    channel("ma_chaine", mode="auto")

    watch.check("ma_chaine", NOW, lister=FakeLister([_vod(VOD_A), _vod(VOD_B)]), config=config)

    queue = _queue(tmp_path)
    assert [(e["video_id"], e["url"], e["action"], e["channel"]) for e in queue] == [
        (VOD_A, f"https://youtu.be/{VOD_A}", "run", "ma_chaine"),
        (VOD_B, f"https://youtu.be/{VOD_B}", "run", "ma_chaine"),
    ]
    state = _state(tmp_path)
    assert state["seen"] == [VOD_A, VOD_B] and state["pending"] == []


def test_check_auto_mode_vod_already_waiting_in_the_queue_is_just_seen(env):
    from clipper import worker

    config, channel, tmp_path = env
    channel("ma_chaine", mode="auto")
    worker.enqueue(f"https://youtu.be/{VOD_A}", None, "run", config=config)

    watch.check("ma_chaine", NOW, lister=FakeLister([_vod(VOD_A)]), config=config)

    assert len(_queue(tmp_path)) == 1
    assert _state(tmp_path)["seen"] == [VOD_A]


def test_check_review_mode_adds_to_pending_and_leaves_the_queue_alone(env):
    config, channel, tmp_path = env
    channel("ma_chaine", mode="review")

    watch.check("ma_chaine", NOW, lister=FakeLister([_vod(VOD_A)]), config=config)

    assert _queue(tmp_path) == []
    state = _state(tmp_path)
    assert [v["video_id"] for v in state["pending"]] == [VOD_A] and state["seen"] == []


def test_check_mode_defaults_to_the_global_mode_when_the_channel_has_none(env):
    config, _channel, tmp_path = env
    (tmp_path / "presets" / "ma_chaine.toml").write_text(
        f'[channel]\nsource_url = "{SOURCE_URL}"\nwatch = true\n', encoding="utf-8")

    watch.check("ma_chaine", NOW, lister=FakeLister([_vod(VOD_A)]), config=config)

    assert [v["video_id"] for v in _state(tmp_path)["pending"]] == [VOD_A]  # config.toml : review


def test_check_without_source_url_is_an_explicit_error(env):
    config, channel, tmp_path = env
    channel("ma_chaine", source_url="")

    with pytest.raises(watch.WatchError, match="source_url"):
        watch.check("ma_chaine", NOW, lister=FakeLister([]), config=config)


# --------------------------------------------------------------------------
# (3) confirm / ignore
# --------------------------------------------------------------------------


def _with_pending(env):
    config, channel, tmp_path = env
    channel("ma_chaine", mode="review")
    watch.check("ma_chaine", NOW, lister=FakeLister([_vod(VOD_A), _vod(VOD_B)]), config=config)
    return config, tmp_path


def test_confirm_enqueues_and_removes_from_pending(env):
    config, tmp_path = _with_pending(env)

    entry = watch.confirm("ma_chaine", VOD_A, config=config)

    queue = _queue(tmp_path)
    assert [(e["video_id"], e["action"], e["channel"], e["url"]) for e in queue] == [
        (VOD_A, "run", "ma_chaine", f"https://youtu.be/{VOD_A}")]
    assert entry["video_id"] == VOD_A
    state = _state(tmp_path)
    assert [v["video_id"] for v in state["pending"]] == [VOD_B]
    assert VOD_A in state["seen"]  # sinon le prochain check la retrouverait comme nouvelle


def test_confirmed_vod_is_not_found_again_by_the_next_check(env):
    config, tmp_path = _with_pending(env)
    watch.confirm("ma_chaine", VOD_A, config=config)

    watch.check("ma_chaine", NOW + timedelta(hours=1), lister=FakeLister([_vod(VOD_A)]), config=config)

    assert [v["video_id"] for v in _state(tmp_path)["pending"]] == [VOD_B]


def test_ignore_moves_to_seen_without_enqueueing(env):
    config, tmp_path = _with_pending(env)

    watch.ignore("ma_chaine", VOD_B, config=config)

    assert _queue(tmp_path) == []
    state = _state(tmp_path)
    assert [v["video_id"] for v in state["pending"]] == [VOD_A]
    assert state["seen"] == [VOD_B]


@pytest.mark.parametrize("action", ["confirm", "ignore"])
def test_confirm_and_ignore_unknown_vod_is_an_explicit_error(env, action):
    config, tmp_path = _with_pending(env)

    with pytest.raises(watch.WatchError, match="ZZZZZZZZZZZ"):
        getattr(watch, action)("ma_chaine", "ZZZZZZZZZZZ", config=config)

    assert [v["video_id"] for v in _state(tmp_path)["pending"]] == [VOD_A, VOD_B]
    assert _queue(tmp_path) == []


# --------------------------------------------------------------------------
# (4) erreur du listeur
# --------------------------------------------------------------------------


def test_lister_exception_writes_last_error_and_keeps_seen_and_pending(env):
    config, channel, tmp_path = env
    channel("ma_chaine")
    before = {"checked_at": None, "seen": [VOD_A], "pending": [_vod(VOD_B, found_at="x")], "last_error": None}
    _write_state(tmp_path, before)

    watch.check("ma_chaine", NOW, lister=FakeLister(error=RuntimeError("reseau coupe")), config=config)

    state = _state(tmp_path)
    assert "reseau coupe" in state["last_error"]
    assert state["seen"] == before["seen"] and state["pending"] == before["pending"]
    assert state["checked_at"] == NOW.isoformat()  # la chaine n'est pas re-interrogee a chaque tick


def test_successful_check_clears_last_error(env):
    config, channel, tmp_path = env
    channel("ma_chaine")
    watch.check("ma_chaine", NOW, lister=FakeLister(error=RuntimeError("boum")), config=config)

    watch.check("ma_chaine", NOW + timedelta(hours=1), lister=FakeLister([]), config=config)

    assert _state(tmp_path)["last_error"] is None


def test_unreadable_state_file_is_an_explicit_error(env):
    config, channel, tmp_path = env
    channel("ma_chaine")
    path = tmp_path / "state" / "watch" / "ma_chaine.json"
    path.parent.mkdir(parents=True)
    path.write_text("{pas du json", encoding="utf-8")

    with pytest.raises(watch.WatchError, match="ma_chaine.json"):
        watch.check("ma_chaine", NOW, lister=FakeLister([]), config=config)


# --------------------------------------------------------------------------
# is_due (utilise par le worker, critere 5)
# --------------------------------------------------------------------------


def test_is_due_when_never_checked_or_interval_elapsed(env):
    config, channel, tmp_path = env
    channel("ma_chaine")
    assert watch.is_due("ma_chaine", 1800, NOW, config=config) is True

    _write_state(tmp_path, {"checked_at": (NOW - timedelta(seconds=1799)).isoformat(),
                            "seen": [], "pending": [], "last_error": None})
    assert watch.is_due("ma_chaine", 1800, NOW, config=config) is False

    _write_state(tmp_path, {"checked_at": (NOW - timedelta(seconds=1800)).isoformat(),
                            "seen": [], "pending": [], "last_error": None})
    assert watch.is_due("ma_chaine", 1800, NOW, config=config) is True


# --------------------------------------------------------------------------
# (6) le vrai listeur
# --------------------------------------------------------------------------


class _FakeYdl:
    def __init__(self, info):
        self._info = info
        self.opts = None
        self.urls: list[str] = []

    def factory(self, opts):
        self.opts = opts
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        assert download is False
        self.urls.append(url)
        return self._info


def test_real_lister_is_the_default_lister(monkeypatch):
    seen = []
    monkeypatch.setattr(watch, "list_vods", lambda url: seen.append(url) or [])
    assert watch._default_lister() is watch.list_vods
    watch._default_lister()(SOURCE_URL)
    assert seen == [SOURCE_URL]


def test_list_vods_uses_flat_extraction_and_normalizes_entries():
    info = {"entries": [
        {"entries": [  # onglet imbrique (chaine YouTube : onglet Videos / En direct)
            {"id": VOD_A, "url": f"https://youtu.be/{VOD_A}", "title": "Un", "duration": 7200,
             "timestamp": 1767297600, "live_status": "was_live"},
            {"id": VOD_B, "url": f"https://youtu.be/{VOD_B}", "title": "En cours", "duration": None,
             "live_status": "is_live"},
        ]},
        {"id": "v123", "url": "https://www.twitch.tv/videos/123", "title": "Deux", "duration": 3600,
         "upload_date": "20260101"},
    ]}
    ydl = _FakeYdl(info)

    vods = watch.list_vods(SOURCE_URL, ydl_factory=ydl.factory)

    assert ydl.urls == [SOURCE_URL]
    assert ydl.opts["extract_flat"] is True and ydl.opts["skip_download"] is True
    assert [v["video_id"] for v in vods] == [VOD_A, "v123"]  # le direct en cours n'est pas une VOD
    assert vods[0] == {"video_id": VOD_A, "url": f"https://youtu.be/{VOD_A}", "title": "Un", "duration_s": 7200,
                       "published_at": "2026-01-01T20:00:00+00:00"}
    assert vods[1]["published_at"] == "2026-01-01T00:00:00+00:00"


def test_list_vods_entry_without_url_is_an_explicit_error():
    ydl = _FakeYdl({"entries": [{"id": VOD_A, "title": "Sans url", "duration": 7200}]})
    with pytest.raises(watch.WatchError, match=VOD_A):
        watch.list_vods(SOURCE_URL, ydl_factory=ydl.factory)


@pytest.mark.skipif(os.environ.get("CLIPPER_REAL_NETWORK") != "1",
                    reason="reseau reel : positionner CLIPPER_REAL_NETWORK=1 (et CLIPPER_REAL_WATCH_URL)")
def test_real_lister_lists_a_real_channel_page():
    url = os.environ.get("CLIPPER_REAL_WATCH_URL")
    assert url, "CLIPPER_REAL_WATCH_URL : page de chaine a lister"
    vods = watch.list_vods(url)
    assert isinstance(vods, list)
    for vod in vods:
        assert vod["video_id"] and vod["url"]
