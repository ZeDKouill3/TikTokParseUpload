"""Clips courts (TASK-4f5e) : [moments] short_clips, short_min, short_max."""
from __future__ import annotations

import json

import pytest

from clipper import llm
from clipper.llm.fake import FakeBackend

from test_moments import (  # noqa: F401  (fixtures reutilisees)
    TEST_RUBRIC, VIDEO_ID, make_config, moment, read_moments, spans, video_dir,
)

# Grille « longue » : 60-120 s, comme rubric.toml ; short_min/short_max (20-45 s)
# ne valent donc pas les bornes de la grille.
LONG_RUBRIC = TEST_RUBRIC.replace("single_min = 20\nsingle_max = 45", "single_min = 60\nsingle_max = 120").replace(
    "part_min = 60\npart_max = 90", "part_min = 60\npart_max = 120"
)


@pytest.fixture
def long_rubric(tmp_path):
    p = tmp_path / "rubric.toml"
    p.write_text(LONG_RUBRIC, encoding="utf-8")
    return p


_UNSET = object()


def go(tmp_path, rubric, responses, *, short_clips=None, short_clips_style=_UNSET, **moments):
    """``short_clips`` : option de la video (None = non precise) ;
    ``short_clips_style`` : [moments] short_clips du style."""
    if short_clips_style is not _UNSET:
        moments["short_clips"] = short_clips_style
    from clipper.moments import run as run_moments

    fake = FakeBackend(responses)
    config = make_config(tmp_path, rubric, **moments)
    kwargs = {} if short_clips is None else {"short_clips": short_clips}
    with llm.use_backend(fake):
        run_moments(VIDEO_ID, tmp_path / "workspace", config=config, **kwargs)
    return fake


# 30 s : valide en court, trop court pour la grille longue ; 74 s : l'inverse.
SHORT_30 = moment(10.25, 39.65)
LONG_74 = moment(100.25, 174.65)


def test_defaults_declare_the_switch_off():
    from clipper.moments import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["short_clips"] is False
    assert (CONFIG_DEFAULTS["short_min"], CONFIG_DEFAULTS["short_max"]) == (20, 45)


def test_off_keeps_the_grid_bounds_and_the_prompt(tmp_path, video_dir, long_rubric):
    fake = go(tmp_path, long_rubric, [{"moments": [SHORT_30, LONG_74]}])

    data = read_moments(video_dir)
    assert spans(data) == [(100.25, 174.65)]
    prompt = fake.calls[0].prompt
    assert "de 60 a 120 s" in prompt
    assert "2 premieres secondes" not in prompt
    assert data["short_clips"] is False
    assert data["rubric"]["path"] == str(long_rubric)
    assert not (video_dir / "rubric-short.toml").exists()


def test_off_prompt_is_the_same_whether_default_or_explicit(tmp_path, video_dir, long_rubric):
    implicit = go(tmp_path, long_rubric, [{"moments": []}]).calls[0].prompt
    (video_dir / "moments.json").unlink()
    explicit = go(tmp_path, long_rubric, [{"moments": []}], short_clips=False).calls[0].prompt
    assert implicit == explicit


def test_on_replaces_the_grid_bounds_and_demands_an_immediate_hook(tmp_path, video_dir, long_rubric):
    fake = go(tmp_path, long_rubric, [{"moments": [SHORT_30, LONG_74]}], short_clips=True)

    data = read_moments(video_dir)
    assert spans(data) == [(10.25, 39.65)]
    prompt = fake.calls[0].prompt
    assert "de 20 a 45 s" in prompt
    assert "de 60 a 120 s" not in prompt
    assert "2 premieres secondes" in prompt
    assert "comprehensible seul" in prompt
    assert (data["short_clips"], data["short_min"], data["short_max"]) == (True, 20, 45)


def test_on_from_config_and_custom_bounds(tmp_path, video_dir, long_rubric):
    fake = go(tmp_path, long_rubric, [{"moments": [SHORT_30, moment(100.25, 114.65)]}],
              short_clips=True, short_min=25, short_max=35)

    assert spans(read_moments(video_dir)) == [(10.25, 39.65)]
    assert "de 25 a 35 s" in fake.calls[0].prompt


def test_style_value_is_used_when_the_video_does_not_say(tmp_path, video_dir, long_rubric):
    go(tmp_path, long_rubric, [{"moments": [SHORT_30]}], short_clips_style=True)
    assert read_moments(video_dir)["short_clips"] is True


def test_video_override_off_beats_style_on(tmp_path, video_dir, long_rubric):
    go(tmp_path, long_rubric, [{"moments": [LONG_74]}], short_clips=False, short_clips_style=True)
    data = read_moments(video_dir)
    assert data["short_clips"] is False
    assert spans(data) == [(100.25, 174.65)]


def test_series_parts_follow_the_short_bounds(tmp_path, video_dir, long_rubric):
    from clipper.parts import load_durations

    go(tmp_path, long_rubric, [{"moments": [moment(250.25, 369.65, fmt="multipart")]}], short_clips=True)

    data = read_moments(video_dir)
    effective = load_durations(data["rubric"]["path"])  # ce que lit l'etape parts
    assert (effective["single_min"], effective["single_max"]) == (20, 45)
    assert (effective["part_min"], effective["part_max"]) == (20, 45)
    assert effective["tolerance"] == 3
    assert data["rubric"]["source"] == str(long_rubric)  # la grille d'origine reste nommee


@pytest.mark.parametrize("bad", ["oui", 1])
def test_invalid_switch_in_the_style_is_an_explicit_error(tmp_path, video_dir, long_rubric, bad):
    from clipper.moments import MomentsError

    with pytest.raises(MomentsError, match="short_clips"):
        go(tmp_path, long_rubric, [{"moments": []}], short_clips_style=bad)
    assert not (video_dir / "moments.json").exists()


def test_invalid_switch_for_the_video_is_an_explicit_error(tmp_path, video_dir, long_rubric):
    from clipper.moments import MomentsError

    with pytest.raises(MomentsError, match="short_clips"):
        go(tmp_path, long_rubric, [{"moments": []}], short_clips="oui")


@pytest.mark.parametrize(
    "settings",
    [{"short_min": 45, "short_max": 20}, {"short_min": 30, "short_max": 30}, {"short_min": 0, "short_max": 45},
     {"short_min": "20", "short_max": 45}, {"short_min": 20, "short_max": True}],
)
def test_invalid_bounds_are_an_explicit_error_when_on(tmp_path, video_dir, long_rubric, settings):
    from clipper.moments import MomentsError

    with pytest.raises(MomentsError, match="short_m"):
        go(tmp_path, long_rubric, [{"moments": []}], short_clips=True, **settings)


def test_rescore_after_vision_keeps_the_short_grid_for_parts(tmp_path, video_dir, long_rubric):
    import os

    from clipper.parts import load_durations

    go(tmp_path, long_rubric, [{"moments": [SHORT_30]}], short_clips=True)
    before = read_moments(video_dir)["rubric"]
    vision = video_dir / "vision.json"
    vision.write_text(json.dumps({"frames": []}), encoding="utf-8")
    future = (video_dir / "moments.json").stat().st_mtime + 10
    os.utime(vision, (future, future))

    go(tmp_path, long_rubric, [], short_clips=True)  # re-notation, aucun appel LLM

    data = read_moments(video_dir)
    assert "rescored" in data
    assert (data["rubric"]["path"], data["rubric"]["source"]) == (before["path"], before["source"])
    assert load_durations(data["rubric"]["path"])["part_max"] == 45
    assert data["short_clips"] is True
