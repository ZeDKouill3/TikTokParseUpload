from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_workspace_dir_is_root_slash_video_id(isolated_cwd):
    from clipper.workspace import Workspace

    ws = Workspace("abc123", root=isolated_cwd / "workspace")

    assert ws.dir == isolated_cwd / "workspace" / "abc123"


def test_workspace_step_is_not_done_until_marked(isolated_cwd):
    from clipper.workspace import Workspace

    ws = Workspace("abc123", root=isolated_cwd / "workspace")

    assert ws.is_done("transcribe") is False

    ws.mark_done("transcribe", {"text": "hello"})

    assert ws.is_done("transcribe") is True


def test_workspace_skips_a_done_step_unless_forced(isolated_cwd):
    from clipper.workspace import Workspace

    ws = Workspace("abc123", root=isolated_cwd / "workspace")

    assert ws.should_run("transcribe") is True

    ws.mark_done("transcribe", {"text": "hello"})

    assert ws.should_run("transcribe") is False
    assert ws.should_run("transcribe", force=True) is True


def test_gitignore_excludes_workspace_and_output_dirs():
    lines = (REPO_ROOT / ".gitignore").read_text().splitlines()

    assert "workspace/" in lines
    assert "output/" in lines


# --------------------------------------------------------------------------
# Purge des fichiers lourds (TASK-886a)
# --------------------------------------------------------------------------

import json  # noqa: E402

import pytest  # noqa: E402

from clipper import workspace as ws_mod  # noqa: E402

VID = "abcdefghijk"


def _make_video(root, video_id=VID, status="done"):
    d = root / "workspace" / video_id
    for rel, size in {
        f"{video_id}.mp4": 1000, "transcribe_audio.wav": 400, "frames/f1.jpg": 30, "frames/f2.jpg": 20,
        "qa/01.jpg": 10, "vision_resize_tmp/a.jpg": 5, "render/03-p1/tmp.mp4": 200,
        "pipeline.json": 3, "meta.json": 3, "transcript.json": 3, "moments.json": 3, "captions.json": 3,
        "thumbnails/_source.jpg": 3, "subtitles/c.ass": 3, "reframe/c.json": 3, "scenes.json": 3,
    }.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    (d / "pipeline.json").write_text(json.dumps({"video_id": video_id, "status": status}), encoding="utf-8")
    return d


def _add_clip(root, clip_id="01-p1", video_id=VID):
    out = root / "output" / video_id
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{clip_id}.mp4").write_bytes(b"y" * 500)
    (out / f"{clip_id}.json").write_text(json.dumps({"video_id": video_id, "clip_id": clip_id}), encoding="utf-8")


def _purge(root, video_id=VID):
    return ws_mod.purge_heavy(video_id, root / "workspace", queue_path=root / "queue.json")


def test_purge_heavy_deletes_heavy_files_keeps_display_files_and_reports_size(isolated_cwd):
    d = _make_video(isolated_cwd)

    assert ws_mod.heavy_size(VID, isolated_cwd / "workspace") == 1000 + 400 + 50 + 10 + 5 + 200
    freed = _purge(isolated_cwd)

    assert freed == 1665
    for gone in (f"{VID}.mp4", "transcribe_audio.wav", "frames", "qa", "vision_resize_tmp", "render"):
        assert not (d / gone).exists(), gone
    for kept in ("pipeline.json", "meta.json", "transcript.json", "moments.json", "captions.json",
                 "thumbnails/_source.jpg", "subtitles/c.ass", "reframe/c.json", "scenes.json"):
        assert (d / kept).is_file(), kept
    assert ws_mod.is_purged(VID, isolated_cwd / "workspace")


def test_purge_heavy_refuses_a_running_video(isolated_cwd):
    d = _make_video(isolated_cwd, status="running")

    with pytest.raises(ws_mod.PurgeRefused, match="en cours"):
        _purge(isolated_cwd)

    assert (d / f"{VID}.mp4").is_file()


def test_purge_heavy_refuses_a_video_in_the_queue(isolated_cwd):
    d = _make_video(isolated_cwd)
    (isolated_cwd / "queue.json").write_text(json.dumps([{"video_id": VID, "status": "waiting"}]), encoding="utf-8")

    with pytest.raises(ws_mod.PurgeRefused, match="file"):
        _purge(isolated_cwd)

    assert (d / f"{VID}.mp4").is_file()


def test_purge_heavy_unknown_video_is_explicit(isolated_cwd):
    with pytest.raises(ws_mod.PurgeRefused, match="introuvable"):
        _purge(isolated_cwd, "zzzzzzzzzzz")


def test_purge_clips_deletes_output_and_returns_size(isolated_cwd):
    _make_video(isolated_cwd)
    _add_clip(isolated_cwd)

    freed = ws_mod.purge_clips(VID, isolated_cwd / "output", isolated_cwd / "publish")

    assert freed > 500
    assert not (isolated_cwd / "output" / VID).exists()


@pytest.mark.parametrize("status", ["approved", "scheduled", "failed"])
def test_purge_clips_refuses_a_pending_publication_and_names_the_clip(isolated_cwd, status):
    _add_clip(isolated_cwd, "02-p2")
    pub = isolated_cwd / "publish"
    pub.mkdir()
    (pub / "style.json").write_text(json.dumps([
        {"video_id": VID, "clip_id": "02-p2", "status": status},
        {"video_id": "other", "clip_id": "01", "status": "approved"}]), encoding="utf-8")

    with pytest.raises(ws_mod.PurgeRefused, match="02-p2"):
        ws_mod.purge_clips(VID, isolated_cwd / "output", pub)

    assert (isolated_cwd / "output" / VID / "02-p2.mp4").is_file()


def test_purge_clips_refuses_an_in_progress_publication(isolated_cwd):
    _add_clip(isolated_cwd, "02-p2")
    pub = isolated_cwd / "publish"
    pub.mkdir()
    (pub / "_sans_chaine.json").write_text(json.dumps([
        {"video_id": VID, "clip_id": "02-p2", "status": "published", "in_progress_since": "2026-01-01T00:00:00+00:00"}]),
        encoding="utf-8")

    with pytest.raises(ws_mod.PurgeRefused, match="02-p2"):
        ws_mod.purge_clips(VID, isolated_cwd / "output", pub)


def test_purge_clips_allows_published_and_rejected(isolated_cwd):
    _add_clip(isolated_cwd)
    pub = isolated_cwd / "publish"
    pub.mkdir()
    (pub / "style.json").write_text(json.dumps([
        {"video_id": VID, "clip_id": "01-p1", "status": "published"}]), encoding="utf-8")

    assert ws_mod.purge_clips(VID, isolated_cwd / "output", pub) > 0


def test_purge_clips_unreadable_publish_file_is_explicit(isolated_cwd):
    _add_clip(isolated_cwd)
    pub = isolated_cwd / "publish"
    pub.mkdir()
    (pub / "style.json").write_text("{pas du json", encoding="utf-8")

    with pytest.raises(ws_mod.PurgeRefused, match="style.json"):
        ws_mod.purge_clips(VID, isolated_cwd / "output", pub)


def test_disk_usage_totals_workspace_and_output(isolated_cwd):
    _make_video(isolated_cwd)
    _add_clip(isolated_cwd)

    usage = ws_mod.disk_usage(isolated_cwd / "workspace", isolated_cwd / "output")

    assert usage["output_bytes"] == 500 + len(json.dumps({"video_id": VID, "clip_id": "01-p1"}))
    assert usage["workspace_bytes"] == 1665 + 3 * 8 + len(json.dumps({"video_id": VID, "status": "done"}))


def test_log_records_a_purge(isolated_cwd, caplog):
    _make_video(isolated_cwd)
    with caplog.at_level("INFO", logger="clipper.workspace"):
        _purge(isolated_cwd)
    assert any(VID in r.message and "1665" in r.message for r in caplog.records)


# --------------------------------------------------------------------------
# Suppression de clips choisis (TASK-2322)
# --------------------------------------------------------------------------


def _add_part(root, clip_id, part, total=3, video_id=VID):
    out = root / "output" / video_id
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{clip_id}.mp4").write_bytes(b"y" * 100)
    (out / f"{clip_id}.json").write_text(json.dumps(
        {"video_id": video_id, "clip_id": clip_id, "part": part, "parts_total": total}), encoding="utf-8")


def _publish(root, entries):
    pub = root / "publish"
    pub.mkdir(exist_ok=True)
    (pub / "style.json").write_text(json.dumps(entries), encoding="utf-8")
    return pub


def test_delete_clips_removes_clip_files_and_returns_freed_bytes(isolated_cwd):
    _add_clip(isolated_cwd, "01-p1")
    _add_clip(isolated_cwd, "02-p1")
    out = isolated_cwd / "output" / VID
    (out / "01-p1.jpg").write_bytes(b"z" * 40)
    sidecar_size = (out / "01-p1.json").stat().st_size

    result = ws_mod.delete_clips(VID, ["01-p1"], isolated_cwd / "output", isolated_cwd / "publish")

    assert result["deleted"] == ["01-p1"] and result["video_deleted"] == []
    assert result["freed_bytes"] == 500 + sidecar_size + 40
    assert sorted(p.name for p in out.iterdir()) == ["02-p1.json", "02-p1.mp4"]


def test_delete_clips_does_not_touch_a_clip_whose_id_is_a_prefix(isolated_cwd):
    _add_clip(isolated_cwd, "01")
    _add_clip(isolated_cwd, "01-p1")

    ws_mod.delete_clips(VID, ["01"], isolated_cwd / "output", None)

    assert (isolated_cwd / "output" / VID / "01-p1.mp4").is_file()
    assert not (isolated_cwd / "output" / VID / "01.mp4").exists()


def test_delete_clips_published_clip_loses_video_and_annexes_but_keeps_its_sidecar(isolated_cwd):
    _add_clip(isolated_cwd, "02-p1")
    out = isolated_cwd / "output" / VID
    (out / "02-p1.jpg").write_bytes(b"z" * 40)
    (out / "02-p1.srt").write_bytes(b"s" * 7)
    sidecar_before = (out / "02-p1.json").read_bytes()
    pub = _publish(isolated_cwd, [{"video_id": VID, "clip_id": "02-p1", "status": "published"}])

    result = ws_mod.delete_clips(VID, ["02-p1"], isolated_cwd / "output", pub)

    assert result["deleted"] == []
    assert result["video_deleted"] == ["02-p1"]
    assert result["freed_bytes"] == 500 + 40 + 7
    assert [p.name for p in out.iterdir()] == ["02-p1.json"]
    assert (out / "02-p1.json").read_bytes() == sidecar_before


def test_delete_clips_published_clip_without_video_anymore_frees_nothing_and_does_not_fail(isolated_cwd):
    _add_clip(isolated_cwd, "02-p1")
    (isolated_cwd / "output" / VID / "02-p1.mp4").unlink()
    pub = _publish(isolated_cwd, [{"video_id": VID, "clip_id": "02-p1", "status": "published"}])

    result = ws_mod.delete_clips(VID, ["02-p1"], isolated_cwd / "output", pub)

    assert result["video_deleted"] == ["02-p1"] and result["freed_bytes"] == 0
    assert (isolated_cwd / "output" / VID / "02-p1.json").is_file()


def test_delete_clips_mixed_series_each_part_follows_its_own_rule(isolated_cwd):
    for n in (1, 2, 3):
        _add_part(isolated_cwd, f"01-p{n}", n)
    pub = _publish(isolated_cwd, [{"video_id": VID, "clip_id": "01-p2", "status": "published"},
                                  {"video_id": VID, "clip_id": "01-p3", "status": "rejected"}])

    result = ws_mod.delete_clips(VID, ["01-p1"], isolated_cwd / "output", pub)

    assert result["deleted"] == ["01-p1", "01-p3"]
    assert result["video_deleted"] == ["01-p2"]
    assert sorted(p.name for p in (isolated_cwd / "output" / VID).iterdir()) == ["01-p2.json"]


def test_delete_clips_published_part_does_not_unblock_a_scheduled_sibling(isolated_cwd):
    for n in (1, 2):
        _add_part(isolated_cwd, f"01-p{n}", n, total=2)
    pub = _publish(isolated_cwd, [{"video_id": VID, "clip_id": "01-p1", "status": "published"},
                                  {"video_id": VID, "clip_id": "01-p2", "status": "scheduled"}])

    with pytest.raises(ws_mod.PurgeRefused, match="01-p2"):
        ws_mod.delete_clips(VID, ["01-p1"], isolated_cwd / "output", pub)

    assert len(list((isolated_cwd / "output" / VID).glob("*.mp4"))) == 2


def test_delete_clips_logs_the_video_only_deletions(isolated_cwd, caplog):
    _add_clip(isolated_cwd, "02-p1")
    pub = _publish(isolated_cwd, [{"video_id": VID, "clip_id": "02-p1", "status": "published"}])

    with caplog.at_level("INFO", logger="clipper.workspace"):
        ws_mod.delete_clips(VID, ["02-p1"], isolated_cwd / "output", pub)

    assert any("02-p1" in r.message and "500" in r.message for r in caplog.records)


@pytest.mark.parametrize("status", ["approved", "scheduled", "failed"])
def test_delete_clips_refuses_pending_and_names_the_clip(isolated_cwd, status):
    _add_clip(isolated_cwd, "02-p2")
    pub = _publish(isolated_cwd, [{"video_id": VID, "clip_id": "02-p2", "status": status}])

    with pytest.raises(ws_mod.PurgeRefused, match="02-p2"):
        ws_mod.delete_clips(VID, ["02-p2"], isolated_cwd / "output", pub)

    assert (isolated_cwd / "output" / VID / "02-p2.mp4").is_file()
    assert (isolated_cwd / "output" / VID / "02-p2.json").is_file()


def test_delete_clips_refuses_an_in_progress_publication(isolated_cwd):
    _add_clip(isolated_cwd, "02-p2")
    pub = _publish(isolated_cwd, [{"video_id": VID, "clip_id": "02-p2", "status": "rejected",
                                   "in_progress_since": "2026-01-01T00:00:00+00:00"}])

    with pytest.raises(ws_mod.PurgeRefused, match="02-p2"):
        ws_mod.delete_clips(VID, ["02-p2"], isolated_cwd / "output", pub)


def test_delete_clips_allows_a_rejected_clip_and_ignores_other_videos_entries(isolated_cwd):
    _add_clip(isolated_cwd, "01-p1")
    pub = _publish(isolated_cwd, [{"video_id": VID, "clip_id": "01-p1", "status": "rejected"},
                                  {"video_id": "other", "clip_id": "01-p1", "status": "published"}])

    assert ws_mod.delete_clips(VID, ["01-p1"], isolated_cwd / "output", pub)["deleted"] == ["01-p1"]


def test_delete_clips_removes_the_whole_series_when_one_part_is_chosen(isolated_cwd):
    for n in (1, 2, 3):
        _add_part(isolated_cwd, f"01-p{n}", n)
    _add_clip(isolated_cwd, "05-p1")

    result = ws_mod.delete_clips(VID, ["01-p2"], isolated_cwd / "output", None)

    assert result["deleted"] == ["01-p1", "01-p2", "01-p3"]
    assert sorted(p.name for p in (isolated_cwd / "output" / VID).iterdir()) == ["05-p1.json", "05-p1.mp4"]


def test_delete_clips_refuses_the_whole_series_when_one_part_is_blocked(isolated_cwd):
    for n in (1, 2, 3):
        _add_part(isolated_cwd, f"01-p{n}", n)
    pub = _publish(isolated_cwd, [{"video_id": VID, "clip_id": "01-p3", "status": "scheduled"}])

    with pytest.raises(ws_mod.PurgeRefused, match="01-p3"):
        ws_mod.delete_clips(VID, ["01-p1"], isolated_cwd / "output", pub)

    assert len(list((isolated_cwd / "output" / VID).glob("*.mp4"))) == 3


def test_delete_clips_unknown_clip_is_explicit(isolated_cwd):
    _add_clip(isolated_cwd, "01-p1")

    with pytest.raises(ws_mod.PurgeRefused, match="zz"):
        ws_mod.delete_clips(VID, ["zz"], isolated_cwd / "output", None)


def test_delete_clips_unreadable_publish_file_is_explicit(isolated_cwd):
    _add_clip(isolated_cwd, "01-p1")
    pub = isolated_cwd / "publish"
    pub.mkdir()
    (pub / "style.json").write_text("{pas du json", encoding="utf-8")

    with pytest.raises(ws_mod.PurgeRefused, match="style.json"):
        ws_mod.delete_clips(VID, ["01-p1"], isolated_cwd / "output", pub)

    assert (isolated_cwd / "output" / VID / "01-p1.mp4").is_file()


def test_series_clip_ids_groups_parts_and_leaves_single_clips_alone(isolated_cwd):
    for n in (1, 2):
        _add_part(isolated_cwd, f"01-p{n}", n, total=2)
    _add_clip(isolated_cwd, "05-p1")

    assert ws_mod.series_clip_ids(VID, "01-p2", isolated_cwd / "output") == ["01-p1", "01-p2"]
    assert ws_mod.series_clip_ids(VID, "05-p1", isolated_cwd / "output") == ["05-p1"]
