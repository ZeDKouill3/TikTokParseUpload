"""Option --short-clips / --no-short-clips de run et render (TASK-4f5e)."""
from __future__ import annotations

import pytest

from clipper import pipeline
from clipper.__main__ import main

from test_pipeline import URL, VIDEO_ID


@pytest.mark.parametrize("flags, expected", [([], None), (["--short-clips"], True), (["--no-short-clips"], False)])
def test_run_and_render_pass_the_video_choice_to_the_pipeline(tmp_path, isolated_cwd, monkeypatch, flags, expected):
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda url, **kw: calls.append(("run", kw["short_clips"])) or {"status": "done"})
    monkeypatch.setattr(pipeline, "render", lambda vid, **kw: calls.append(("render", kw["short_clips"])) or {"status": "done"})

    assert main(["run", URL, *flags]) == 0
    assert main(["render", VIDEO_ID, *flags]) == 0
    assert calls == [("run", expected), ("render", expected)]
