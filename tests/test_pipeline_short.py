"""short_clips voyage de pipeline.run/render jusqu'a l'etape moments (TASK-4f5e)."""
from __future__ import annotations

import pytest

from clipper import moments, pipeline
from clipper.config import Config

from test_pipeline import URL, VIDEO_ID


def _spy_moments(monkeypatch):
    seen = []
    monkeypatch.setattr(moments, "run", lambda *a, **kw: seen.append(kw.get("short_clips", "absent")))
    monkeypatch.setattr(pipeline.feedback, "examples", lambda *a, **kw: [])
    return seen


def _run_step(tmp_path, short_clips):
    config = Config(mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")
    state = pipeline.new_state(VIDEO_ID, URL, "auto")
    captured = {}
    orig = pipeline._advance
    pipeline._advance = lambda run, **kw: captured.setdefault("run", run) and state
    try:
        pipeline.run(URL, config=config, short_clips=short_clips)
    finally:
        pipeline._advance = orig
    return captured["run"]


@pytest.mark.parametrize("value", [None, True, False])
def test_run_hands_the_choice_to_the_moments_step(tmp_path, monkeypatch, value):
    seen = _spy_moments(monkeypatch)
    _run_step(tmp_path, value).moments()
    assert seen == ["absent" if value is None else value]  # non precise : l etape ne recoit rien


def test_a_non_boolean_choice_is_an_explicit_error(tmp_path):
    config = Config(mode="auto", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output")
    with pytest.raises(pipeline.PipelineError, match="short_clips"):
        pipeline.run(URL, config=config, short_clips="oui")
