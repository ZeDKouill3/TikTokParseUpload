"""Clips courts par video dans la file (TASK-4f5e)."""
from __future__ import annotations

import sys

import pytest

from clipper import worker

from test_worker import URL_A, VIDEO_A, _cmd_entry, _config, _parse_built, _queue


def test_enqueue_stores_the_video_choice(tmp_path):
    config = _config(tmp_path)
    entry = worker.enqueue(URL_A, None, "run", None, config=config, short_clips=True)
    assert entry["short_clips"] is True
    assert _queue(config)[0]["short_clips"] is True


def test_enqueue_without_choice_keeps_the_old_entry_shape(tmp_path):
    config = _config(tmp_path)
    entry = worker.enqueue(URL_A, None, "run", None, config=config)
    assert "short_clips" not in entry


def test_enqueue_stores_an_explicit_off(tmp_path):
    entry = worker.enqueue(URL_A, None, "run", None, config=_config(tmp_path), short_clips=False)
    assert entry["short_clips"] is False


@pytest.mark.parametrize("bad", ["oui", 1])
def test_enqueue_refuses_a_non_boolean_choice(tmp_path, bad):
    with pytest.raises(worker.WorkerError, match="short_clips"):
        worker.enqueue(URL_A, None, "run", None, config=_config(tmp_path), short_clips=bad)
    assert _queue(_config(tmp_path)) == []


@pytest.mark.parametrize(
    "field, expected, flags",
    [({"short_clips": True}, True, ["--short-clips"]),
     ({"short_clips": False}, False, ["--no-short-clips"]),
     ({}, None, [])],
)
def test_child_command_carries_the_three_states(field, expected, flags):
    entry = {**_cmd_entry("run", None), **field}
    cmd = worker._build_command(entry)
    assert [c for c in cmd if "short-clips" in c] == flags
    assert _parse_built(entry).short_clips is expected


def test_render_child_command_accepts_the_flag_too():
    entry = {**_cmd_entry("render", None), "short_clips": True}
    assert _parse_built(entry).short_clips is True
