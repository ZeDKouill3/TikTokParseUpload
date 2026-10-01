from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


def _write_config(cwd: Path, mode: str = "review") -> None:
    (cwd / "config.toml").write_text(f'mode = "{mode}"\n', encoding="utf-8")


def _write_preset(cwd: Path, name: str, body: str = "[channel]\n") -> Path:
    presets_dir = cwd / "presets"
    presets_dir.mkdir(exist_ok=True)
    path = presets_dir / f"{name}.toml"
    path.write_text(body, encoding="utf-8")
    return path


_SLOT_PRESET = '[channel]\ntimezone = "UTC"\n[[channel.slots]]\nday = "mon"\ntime = "09:00"\n'


def _write_sidecar(
    cwd: Path,
    video_id: str,
    clip_id: str,
    *,
    ready: bool = True,
    qa_status: str = "passed",
    part: int = 1,
    parts_total: int = 1,
    **extra,
) -> Path:
    out_dir = cwd / "output" / video_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{clip_id}.json"
    data = {
        "video_id": video_id,
        "source_url": "https://example.invalid/x",
        "source_title": "titre",
        "clip_id": clip_id,
        "part": part,
        "parts_total": parts_total,
        "start": 0.0,
        "end": 10.0,
        "duration": 10.0,
        "language": "fr",
        "score": 80,
        "scores": {},
        "reason": "raison",
        "hook_text": "accroche",
        "screen_title": "titre ecran",
        "title": "titre",
        "caption": "legende initiale",
        "hashtags": ["#exemple"],
        "transcript": "transcript",
        "layout": "letterbox",
        "qa": {"status": qa_status, "issues": []},
        "created_at": "2026-09-30T00:00:00+00:00",
        "cta": False,
        "ready": ready,
    }
    data.update(extra)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _read_sidecar(cwd: Path, video_id: str, clip_id: str) -> dict:
    path = cwd / "output" / video_id / f"{clip_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _state_file(cwd: Path, channel: str) -> Path:
    return cwd / "state" / "publish" / f"{channel}.json"


def _read_state(cwd: Path, channel: str) -> list[dict]:
    path = _state_file(cwd, channel)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# (1) approve : entree SPEC-fc0c 4.1, slots / sans slots, serie
# --------------------------------------------------------------------------


def test_approve_without_slots_sets_status_approved(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    _write_sidecar(isolated_cwd, "vid1", "03")

    entry = publish.approve("vid1", "03", "ma_chaine")

    assert entry["video_id"] == "vid1"
    assert entry["clip_id"] == "03"
    assert entry["series_id"] is None
    assert entry["part"] is None
    assert entry["status"] == "approved"
    assert entry["slot_at"] is None
    assert entry["published_at"] is None
    assert entry["error"] is None
    assert entry["decided_at"] is not None

    on_disk = _read_state(isolated_cwd, "ma_chaine")
    assert on_disk == [entry]


def test_approve_with_slots_schedules_next_free_slot_after_now(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(
        isolated_cwd, "ma_chaine",
        '[channel]\ntimezone = "UTC"\n[[channel.slots]]\nday = "mon"\ntime = "09:00"\n',
    )
    _write_sidecar(isolated_cwd, "vid1", "03")
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)  # monday, past 09:00

    entry = publish.approve("vid1", "03", "ma_chaine", now=now)

    assert entry["status"] == "scheduled"
    assert entry["slot_at"] == datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("UTC")).isoformat()


def test_approve_series_parts_get_consecutive_slots_in_part_order(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(
        isolated_cwd, "ma_chaine",
        '[channel]\ntimezone = "UTC"\n'
        '[[channel.slots]]\nday = "mon"\ntime = "09:00"\n'
        '[[channel.slots]]\nday = "wed"\ntime = "09:00"\n',
    )
    _write_sidecar(isolated_cwd, "vid1", "03-p1", part=1, parts_total=2)
    _write_sidecar(isolated_cwd, "vid1", "03-p2", part=2, parts_total=2)
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)  # monday, past 09:00

    part1 = publish.approve("vid1", "03-p1", "ma_chaine", now=now)
    part2 = publish.approve("vid1", "03-p2", "ma_chaine", now=now)

    assert part1["series_id"] == part2["series_id"]
    assert part1["series_id"] is not None
    assert part1["part"] == 1
    assert part2["part"] == 2
    assert part1["slot_at"] == datetime(2026, 9, 30, 9, 0, tzinfo=ZoneInfo("UTC")).isoformat()
    assert part2["slot_at"] == datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("UTC")).isoformat()


# --------------------------------------------------------------------------
# (2) approve refuse un clip non pret
# --------------------------------------------------------------------------


def test_approve_refuses_clip_not_ready(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    _write_sidecar(isolated_cwd, "vid1", "03", ready=False)

    with pytest.raises(publish.PublishError, match="vid1/03"):
        publish.approve("vid1", "03", "ma_chaine")

    assert _read_state(isolated_cwd, "ma_chaine") == []


# --------------------------------------------------------------------------
# (3) reject d'une partie rejette toute la serie
# --------------------------------------------------------------------------


def test_reject_a_series_part_rejects_the_whole_series(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    _write_sidecar(isolated_cwd, "vid1", "03-p1", part=1, parts_total=2)
    _write_sidecar(isolated_cwd, "vid1", "03-p2", part=2, parts_total=2)
    publish.approve("vid1", "03-p1", "ma_chaine")

    rejected = publish.reject("vid1", "03-p2", "ma_chaine")

    assert rejected["status"] == "rejected"
    entries = {(e["video_id"], e["clip_id"]): e for e in _read_state(isolated_cwd, "ma_chaine")}
    assert entries[("vid1", "03-p1")]["status"] == "rejected"
    assert entries[("vid1", "03-p1")]["slot_at"] is None
    assert entries[("vid1", "03-p2")]["status"] == "rejected"


def test_reject_a_clip_without_a_series_only_rejects_that_clip(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    _write_sidecar(isolated_cwd, "vid1", "03")
    _write_sidecar(isolated_cwd, "vid1", "04")
    publish.approve("vid1", "04", "ma_chaine")

    publish.reject("vid1", "03", "ma_chaine")

    entries = {(e["video_id"], e["clip_id"]): e for e in _read_state(isolated_cwd, "ma_chaine")}
    assert entries[("vid1", "03")]["status"] == "rejected"
    assert entries[("vid1", "04")]["status"] == "approved"


# --------------------------------------------------------------------------
# (4) move : creneau deja pris / hors des slots de la chaine
# --------------------------------------------------------------------------


def test_move_refuses_a_slot_already_taken(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(
        isolated_cwd, "ma_chaine",
        '[channel]\ntimezone = "UTC"\n'
        '[[channel.slots]]\nday = "mon"\ntime = "09:00"\n'
        '[[channel.slots]]\nday = "wed"\ntime = "09:00"\n',
    )
    _write_sidecar(isolated_cwd, "vid1", "03")
    _write_sidecar(isolated_cwd, "vid1", "04")
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    publish.approve("vid1", "03", "ma_chaine", now=now)  # -> wed 2026-09-30 09:00
    publish.approve("vid1", "04", "ma_chaine", now=now)  # -> mon 2026-10-05 09:00
    taken_slot = datetime(2026, 9, 30, 9, 0, tzinfo=ZoneInfo("UTC"))

    with pytest.raises(publish.PublishError, match="vid1/04"):
        publish.move("vid1", "04", "ma_chaine", taken_slot)


def test_move_refuses_a_slot_outside_the_channel_slots(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(
        isolated_cwd, "ma_chaine",
        '[channel]\ntimezone = "UTC"\n[[channel.slots]]\nday = "mon"\ntime = "09:00"\n',
    )
    _write_sidecar(isolated_cwd, "vid1", "03")
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    publish.approve("vid1", "03", "ma_chaine", now=now)
    out_of_slots = datetime(2026, 10, 1, 9, 0, tzinfo=ZoneInfo("UTC"))  # tuesday

    with pytest.raises(publish.PublishError, match="vid1/03"):
        publish.move("vid1", "03", "ma_chaine", out_of_slots)


def test_move_to_a_free_slot_updates_slot_at(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(
        isolated_cwd, "ma_chaine",
        '[channel]\ntimezone = "UTC"\n'
        '[[channel.slots]]\nday = "mon"\ntime = "09:00"\n'
        '[[channel.slots]]\nday = "wed"\ntime = "09:00"\n',
    )
    _write_sidecar(isolated_cwd, "vid1", "03")
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    publish.approve("vid1", "03", "ma_chaine", now=now)  # -> wed 2026-09-30 09:00
    new_slot = datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("UTC"))  # mon, free

    moved = publish.move("vid1", "03", "ma_chaine", new_slot)

    assert moved["slot_at"] == new_slot.isoformat()
    assert moved["status"] == "scheduled"


# --------------------------------------------------------------------------
# (5) mark_published et unschedule
# --------------------------------------------------------------------------


def test_mark_published_sets_status_and_published_at(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine", _SLOT_PRESET)  # avec creneau : scheduled
    _write_sidecar(isolated_cwd, "vid1", "03")
    publish.approve("vid1", "03", "ma_chaine")
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    entry = publish.mark_published("vid1", "03", "ma_chaine", now=now)

    assert entry["status"] == "published"
    assert entry["published_at"] == now.isoformat()


def test_unschedule_returns_a_scheduled_clip_to_approved(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(
        isolated_cwd, "ma_chaine",
        '[channel]\ntimezone = "UTC"\n[[channel.slots]]\nday = "mon"\ntime = "09:00"\n',
    )
    _write_sidecar(isolated_cwd, "vid1", "03")
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    publish.approve("vid1", "03", "ma_chaine", now=now)

    entry = publish.unschedule("vid1", "03", "ma_chaine")

    assert entry["status"] == "approved"
    assert entry["slot_at"] is None


# --------------------------------------------------------------------------
# (6) edit_caption
# --------------------------------------------------------------------------


def test_edit_caption_rewrites_sidecar_fields_and_edited_at(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    _write_sidecar(isolated_cwd, "vid1", "03")
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

    publish.edit_caption("vid1", "03", "ma_chaine", "nouvelle legende", ["#nouveau"], now=now)

    sidecar = _read_sidecar(isolated_cwd, "vid1", "03")
    assert sidecar["caption"] == "nouvelle legende"
    assert sidecar["hashtags"] == ["#nouveau"]
    assert sidecar["edited_at"] == now.isoformat()


def test_edit_caption_refuses_on_a_scheduled_entry(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(
        isolated_cwd, "ma_chaine",
        '[channel]\ntimezone = "UTC"\n[[channel.slots]]\nday = "mon"\ntime = "09:00"\n',
    )
    _write_sidecar(isolated_cwd, "vid1", "03")
    publish.approve("vid1", "03", "ma_chaine")

    with pytest.raises(publish.PublishError, match="vid1/03"):
        publish.edit_caption("vid1", "03", "ma_chaine", "x", [])


def test_edit_caption_refuses_on_a_published_entry(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine", _SLOT_PRESET)  # avec creneau : scheduled
    _write_sidecar(isolated_cwd, "vid1", "03")
    publish.approve("vid1", "03", "ma_chaine")
    publish.mark_published("vid1", "03", "ma_chaine")

    with pytest.raises(publish.PublishError, match="vid1/03"):
        publish.edit_caption("vid1", "03", "ma_chaine", "x", [])


# --------------------------------------------------------------------------
# (7) list_pending
# --------------------------------------------------------------------------


def test_list_pending_returns_ready_clips_absent_from_the_publish_file(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    _write_sidecar(isolated_cwd, "vid1", "03")
    _write_sidecar(isolated_cwd, "vid1", "04")
    _write_sidecar(isolated_cwd, "vid1", "05", ready=False)
    workspace_dir = isolated_cwd / "workspace" / "vid1"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "pipeline.json").write_text(
        json.dumps({"channel": "ma_chaine"}), encoding="utf-8"
    )
    publish.approve("vid1", "04", "ma_chaine")

    pending = publish.list_pending("ma_chaine")

    assert [clip["clip_id"] for clip in pending] == ["03"]


def test_list_pending_ignores_videos_from_another_channel(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    _write_sidecar(isolated_cwd, "vid1", "03")
    workspace_dir = isolated_cwd / "workspace" / "vid1"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "pipeline.json").write_text(
        json.dumps({"channel": "autre_chaine"}), encoding="utf-8"
    )

    assert publish.list_pending("ma_chaine") == []


# --------------------------------------------------------------------------
# (8) entree invalide
# --------------------------------------------------------------------------


def test_invalid_entry_in_the_file_raises_publish_error_naming_the_field(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    state_dir = isolated_cwd / "state" / "publish"
    state_dir.mkdir(parents=True)
    (state_dir / "ma_chaine.json").write_text(
        json.dumps([{
            "video_id": "vid1", "clip_id": "03", "series_id": None, "part": None,
            "status": "bogus", "slot_at": None, "decided_at": None,
            "published_at": None, "error": None,
        }]),
        encoding="utf-8",
    )

    with pytest.raises(publish.PublishError, match="status"):
        publish.list_pending("ma_chaine")


def test_invalid_entry_missing_a_field_raises_publish_error_naming_it(isolated_cwd):
    from clipper import publish

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    state_dir = isolated_cwd / "state" / "publish"
    state_dir.mkdir(parents=True)
    (state_dir / "ma_chaine.json").write_text(
        json.dumps([{"video_id": "vid1", "clip_id": "03"}]), encoding="utf-8"
    )

    with pytest.raises(publish.PublishError, match="series_id"):
        publish.list_pending("ma_chaine")


# --------------------------------------------------------------------------
# TASK-ded3 : verrou, statuts coherents, ordre des parties, JSON corrompu
# --------------------------------------------------------------------------


def _approve_many(cwd, prefix, n):
    import os

    from clipper import publish

    os.chdir(cwd)
    for i in range(n):
        publish.approve(f"{prefix}vid", f"{i:02d}", "ma_chaine")


def test_approve_from_two_processes_loses_no_entry(isolated_cwd):
    import multiprocessing
    import sys

    _write_config(isolated_cwd)
    _write_preset(isolated_cwd, "ma_chaine")
    for prefix in ("a", "b"):
        for i in range(20):
            _write_sidecar(isolated_cwd, f"{prefix}vid", f"{i:02d}")
    ctx = multiprocessing.get_context("fork" if sys.platform != "win32" else "spawn")
    procs = [ctx.Process(target=_approve_many, args=(isolated_cwd, prefix, 20)) for prefix in ("a", "b")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
        assert p.exitcode == 0

    keys = {(e["video_id"], e["clip_id"]) for e in _read_state(isolated_cwd, "ma_chaine")}
    assert len(keys) == 40


def _seed_entry(cwd, status, clip_id="03"):
    _write_config(cwd)
    _write_preset(
        cwd, "ma_chaine",
        '[channel]\ntimezone = "UTC"\n[[channel.slots]]\nday = "mon"\ntime = "09:00"\n',
    )
    _write_sidecar(cwd, "vid1", clip_id)
    state = _state_file(cwd, "ma_chaine")
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps([{
        "video_id": "vid1", "clip_id": clip_id, "series_id": None, "part": None,
        "status": status, "slot_at": None, "decided_at": "2026-09-28T00:00:00+00:00",
        "published_at": None, "error": None,
    }]), encoding="utf-8")


@pytest.mark.parametrize("status", ["rejected", "published"])
def test_move_refuses_a_rejected_or_published_entry(isolated_cwd, status):
    from clipper import publish

    _seed_entry(isolated_cwd, status)
    slot = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)

    with pytest.raises(publish.PublishError, match=status):
        publish.move("vid1", "03", "ma_chaine", slot)


@pytest.mark.parametrize("status", ["approved", "rejected", "published", "failed"])
def test_mark_published_requires_a_scheduled_entry(isolated_cwd, status):
    from clipper import publish

    _seed_entry(isolated_cwd, status)

    with pytest.raises(publish.PublishError, match="scheduled"):
        publish.mark_published("vid1", "03", "ma_chaine")


def test_mark_published_accepts_a_scheduled_entry(isolated_cwd):
    from clipper import publish

    _seed_entry(isolated_cwd, "scheduled")

    assert publish.mark_published("vid1", "03", "ma_chaine")["status"] == "published"


def _series(cwd):
    _write_config(cwd)
    _write_preset(cwd, "ma_chaine")
    _write_sidecar(cwd, "vid1", "03-p1", part=1, parts_total=3)
    _write_sidecar(cwd, "vid1", "03-p2", part=2, parts_total=3)
    _write_sidecar(cwd, "vid1", "03-p3", part=3, parts_total=3)


def test_approve_part_n_refuses_when_previous_part_was_never_approved(isolated_cwd):
    from clipper import publish

    _series(isolated_cwd)

    with pytest.raises(publish.PublishError, match="03-p1"):
        publish.approve("vid1", "03-p2", "ma_chaine")
    assert _read_state(isolated_cwd, "ma_chaine") == []


def test_approve_part_n_refuses_when_previous_part_is_rejected(isolated_cwd):
    from clipper import publish

    _series(isolated_cwd)
    publish.approve("vid1", "03-p1", "ma_chaine")
    state = _state_file(isolated_cwd, "ma_chaine")
    entries = json.loads(state.read_text(encoding="utf-8"))
    entries[0]["status"] = "rejected"
    state.write_text(json.dumps(entries), encoding="utf-8")

    with pytest.raises(publish.PublishError, match="03-p1"):
        publish.approve("vid1", "03-p2", "ma_chaine")


def test_approve_part_n_accepts_when_previous_part_is_approved(isolated_cwd):
    from clipper import publish

    _series(isolated_cwd)
    publish.approve("vid1", "03-p1", "ma_chaine")
    publish.approve("vid1", "03-p2", "ma_chaine")

    assert publish.approve("vid1", "03-p3", "ma_chaine")["part"] == 3


def test_sibling_clip_ids_raises_publish_error_on_corrupt_json(isolated_cwd):
    from clipper import publish

    _write_sidecar(isolated_cwd, "vid1", "03-p1", part=1, parts_total=2)
    (isolated_cwd / "output" / "vid1" / "03-p2.json").write_text("{pas du json", encoding="utf-8")

    with pytest.raises(publish.PublishError, match="03-p2.json"):
        publish._sibling_clip_ids(isolated_cwd / "output", "vid1", "vid1:03", exclude="03-p1")


# --------------------------------------------------------------------------
# TASK-0b78 : etat de publication TikTok (SPEC-9225 R3, R4, R6)
# --------------------------------------------------------------------------

_ACCOUNT = "ab12cd"
_TWO_SLOTS = (
    f'[channel]\ntimezone = "UTC"\ntiktok_account = "{_ACCOUNT}"\n'
    '[[channel.slots]]\nday = "mon"\ntime = "09:00"\n[[channel.slots]]\nday = "mon"\ntime = "18:00"\n'
)
_MON = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)


def _tiktok_env(cwd, clips=("01", "02", "03"), preset=_TWO_SLOTS):
    _write_config(cwd)
    (cwd / "state").mkdir(exist_ok=True)
    (cwd / "state" / "accounts.json").write_text(
        json.dumps({"accounts": [{"id": _ACCOUNT, "label": "Compte"}]}), encoding="utf-8")
    _write_preset(cwd, "ma_chaine", preset)
    from clipper import publish

    for clip in clips:
        _write_sidecar(cwd, "vid1", clip)
        publish.approve("vid1", clip, "ma_chaine", now=_MON)
    return publish


def test_mark_published_with_a_tiktok_post_records_it_in_the_entry_and_the_sidecar(isolated_cwd):
    publish = _tiktok_env(isolated_cwd, ("01",))
    at = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)

    entry = publish.mark_published(
        "vid1", "01", "ma_chaine", now=at, post_url="https://example.invalid/@ma_chaine/video/42", post_id="42",
        tiktok_state="published", publish_at=at.isoformat(), account=_ACCOUNT)

    assert entry["status"] == "published"
    assert (entry["post_url"], entry["post_id"], entry["tiktok_state"]) == ("https://example.invalid/@ma_chaine/video/42", "42", "published")
    assert entry["tiktok_publish_at"] == at.isoformat()
    assert _read_state(isolated_cwd, "ma_chaine")[0]["post_id"] == "42"
    sidecar = _read_sidecar(isolated_cwd, "vid1", "01")
    assert sidecar["tiktok_post"] == {
        "url": "https://example.invalid/@ma_chaine/video/42", "id": "42", "state": "published",
        "publish_at": at.isoformat(), "account": _ACCOUNT, "note": None}


def test_mark_failed_records_reason_capture_and_halt_then_retry_puts_it_back(isolated_cwd):
    publish = _tiktok_env(isolated_cwd, ("01",))

    entry = publish.mark_failed("vid1", "01", "ma_chaine", "captcha détecté",
                                capture="state/browser/ab12cd/captures/x.png", halted=True)

    assert entry["status"] == "failed"
    assert entry["error"] == "captcha détecté"
    assert entry["capture"] == "state/browser/ab12cd/captures/x.png"
    assert publish.halted_account(_ACCOUNT)["error"] == "captcha détecté"

    retried = publish.retry("vid1", "01", "ma_chaine")

    assert retried["status"] == "scheduled"
    assert retried["slot_at"] == entry["slot_at"]
    assert retried["error"] is None and retried["capture"] is None and not retried["halted"]
    assert publish.halted_account(_ACCOUNT) is None


def test_retry_refuses_an_entry_that_did_not_fail(isolated_cwd):
    publish = _tiktok_env(isolated_cwd, ("01",))
    with pytest.raises(publish.PublishError, match="failed"):
        publish.retry("vid1", "01", "ma_chaine")
    with pytest.raises(publish.PublishError, match="absent"):
        publish.retry("vid1", "99", "ma_chaine")


def test_mark_failed_refuses_a_published_or_unknown_entry(isolated_cwd):
    publish = _tiktok_env(isolated_cwd, ("01",))
    publish.mark_published("vid1", "01", "ma_chaine")
    with pytest.raises(publish.PublishError, match="published"):
        publish.mark_failed("vid1", "01", "ma_chaine", "x")
    with pytest.raises(publish.PublishError, match="absent"):
        publish.mark_failed("vid1", "99", "ma_chaine", "x")


def test_account_publish_times_lists_the_posts_of_every_channel_of_the_account(isolated_cwd):
    publish = _tiktok_env(isolated_cwd, ("01", "02"))
    at = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
    publish.mark_published("vid1", "01", "ma_chaine", now=at, tiktok_state="published", publish_at=at.isoformat(), account=_ACCOUNT)
    later = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
    publish.mark_published("vid1", "02", "ma_chaine", now=at, tiktok_state="scheduled_on_tiktok", publish_at=later.isoformat())
    _write_preset(isolated_cwd, "autre", f'[channel]\ntiktok_account = "{_ACCOUNT}"\n')
    _write_preset(isolated_cwd, "sans_compte", "[channel]\n")

    assert publish.account_publish_times(_ACCOUNT) == [at, later]
    assert publish.account_publish_times("zz99") == []


def test_manually_published_entries_count_by_their_published_at(isolated_cwd):
    publish = _tiktok_env(isolated_cwd, ("01",))
    publish.mark_published("vid1", "01", "ma_chaine", now=_MON)
    assert publish.account_publish_times(_ACCOUNT) == [_MON]


def test_postpone_moves_to_the_next_free_allowed_slot_and_records_why(isolated_cwd):
    publish = _tiktok_env(isolated_cwd, ("01", "02"))  # 01 : lun 09:00, 02 : lun 18:00
    first = publish.list_entries("ma_chaine")[0]
    blocked_until = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)

    entry = publish.postpone(
        "vid1", "01", "ma_chaine", "plafond atteint",
        allowed=lambda slot: "trop tot" if slot < blocked_until else None, now=_MON)

    assert first["slot_at"] == "2026-09-28T09:00:00+00:00"
    assert entry["slot_at"] == "2026-10-05T09:00:00+00:00"  # le 18:00 du 28 est pris par 02 ; le 05 09:00 est libre
    assert entry["status"] == "scheduled"
    assert "plafond atteint" in entry["postponed_reason"] and "2026-10-05" in entry["postponed_reason"]
    assert _read_state(isolated_cwd, "ma_chaine")[0]["slot_at"] == entry["slot_at"]


def test_postpone_without_any_allowed_slot_is_an_explicit_error(isolated_cwd):
    publish = _tiktok_env(isolated_cwd, ("01",))
    with pytest.raises(publish.PublishError, match="créneau"):
        publish.postpone("vid1", "01", "ma_chaine", "plafond", allowed=lambda slot: "jamais", now=_MON)


def test_set_mode_overrides_the_publish_mode_of_one_entry(isolated_cwd):
    publish = _tiktok_env(isolated_cwd, ("01",))
    assert publish.set_mode("vid1", "01", "ma_chaine", "scheduled")["publish_mode"] == "scheduled"
    assert publish.set_mode("vid1", "01", "ma_chaine", None)["publish_mode"] is None
    with pytest.raises(publish.PublishError, match="mode"):
        publish.set_mode("vid1", "01", "ma_chaine", "demain")
