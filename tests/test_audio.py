from __future__ import annotations

import json
import math

import numpy as np
import pytest


def test_compute_energy_db_matches_expected_rms_for_constant_amplitude_windows():
    from clipper.audio import compute_energy_db

    sample_rate = 8000
    amplitude = 0.5
    # 3 windows of 1 s each, constant-amplitude sine wave throughout.
    t = np.arange(3 * sample_rate) / sample_rate
    samples = (amplitude * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
    expected_rms = amplitude / math.sqrt(2)
    expected_db = 20 * math.log10(expected_rms)

    energy_db = compute_energy_db(samples, sample_rate, window_seconds=1.0)

    assert len(energy_db) == 3
    for db in energy_db:
        assert db == pytest.approx(expected_db, abs=0.1)


def _synthetic_signal_with_bursts(sample_rate: int, duration_s: int, burst_times: list[int]):
    """Quiet background noise with a short, much louder burst starting at
    each time in ``burst_times`` (seconds)."""
    rng = np.random.default_rng(0)
    samples = (rng.uniform(-1, 1, duration_s * sample_rate) * 0.01).astype(np.float32)
    burst_len = int(0.5 * sample_rate)
    for t in burst_times:
        start = t * sample_rate
        samples[start : start + burst_len] += 0.9 * np.sin(
            2 * math.pi * 220 * np.arange(burst_len) / sample_rate
        ).astype(np.float32)
    return samples


def test_analyze_finds_known_bursts_within_one_second():
    from clipper.audio import analyze

    sample_rate = 8000
    burst_times = [5, 15, 25]
    samples = _synthetic_signal_with_bursts(sample_rate, duration_s=30, burst_times=burst_times)

    result = analyze(samples, sample_rate)

    peak_times = [p["timecode"] for p in result["peaks"]]
    for expected_t in burst_times:
        assert any(abs(pt - expected_t) <= 1 for pt in peak_times), (
            f"aucun pic pres de t={expected_t}s parmi {peak_times}"
        )


def test_analyze_finds_no_peaks_in_pure_silence():
    from clipper.audio import analyze

    sample_rate = 8000
    rng = np.random.default_rng(1)
    samples = (rng.uniform(-1, 1, 20 * sample_rate) * 0.01).astype(np.float32)

    result = analyze(samples, sample_rate)

    assert result["peaks"] == []


def test_analyze_peak_has_timecode_and_relative_intensity_fields():
    from clipper.audio import analyze

    sample_rate = 8000
    samples = _synthetic_signal_with_bursts(sample_rate, duration_s=15, burst_times=[7])

    result = analyze(samples, sample_rate)

    assert len(result["peaks"]) >= 1
    peak = result["peaks"][0]
    assert set(peak) == {"timecode", "relative_db"}
    assert isinstance(peak["timecode"], (int, float))
    assert peak["relative_db"] > 0


def test_run_writes_audio_json_at_workspace_video_id(isolated_cwd):
    from clipper.audio import run

    sample_rate = 8000
    samples = _synthetic_signal_with_bursts(sample_rate, duration_s=10, burst_times=[3])
    workspace_dir = isolated_cwd / "workspace"
    seen_video_paths = []

    def fake_extractor(video_path, sr):
        seen_video_paths.append(video_path)
        assert sr == sample_rate
        return samples

    result = run(
        "abc123",
        workspace_dir=workspace_dir,
        sample_rate=sample_rate,
        extractor=fake_extractor,
    )

    assert seen_video_paths == [workspace_dir / "abc123" / "abc123.mp4"]
    out_file = workspace_dir / "abc123" / "audio.json"
    assert json.loads(out_file.read_text(encoding="utf-8")) == result
    assert "energy_db" in result
    assert "peaks" in result


def test_run_skips_extraction_when_audio_json_already_present(isolated_cwd):
    from clipper.audio import run

    workspace_dir = isolated_cwd / "workspace"
    video_dir = workspace_dir / "abc123"
    video_dir.mkdir(parents=True)
    existing = {"window_seconds": 1.0, "energy_db": [1.0], "peaks": []}
    (video_dir / "audio.json").write_text(json.dumps(existing), encoding="utf-8")

    def extractor_that_must_not_be_called(video_path, sr):
        raise AssertionError("l'extraction ne doit pas avoir lieu : audio.json existe deja")

    result = run(
        "abc123",
        workspace_dir=workspace_dir,
        extractor=extractor_that_must_not_be_called,
    )

    assert result == existing


def test_run_force_recomputes_even_if_audio_json_present(isolated_cwd):
    from clipper.audio import run

    workspace_dir = isolated_cwd / "workspace"
    video_dir = workspace_dir / "abc123"
    video_dir.mkdir(parents=True)
    (video_dir / "audio.json").write_text(json.dumps({"stale": True}), encoding="utf-8")

    sample_rate = 8000
    samples = _synthetic_signal_with_bursts(sample_rate, duration_s=5, burst_times=[])
    called = []

    def fake_extractor(video_path, sr):
        called.append(video_path)
        return samples

    result = run(
        "abc123",
        workspace_dir=workspace_dir,
        sample_rate=sample_rate,
        extractor=fake_extractor,
        force=True,
    )

    assert called
    assert "stale" not in result


def test_config_defaults_declares_expected_settings():
    from clipper.audio import CONFIG_DEFAULTS

    assert "sample_rate" in CONFIG_DEFAULTS
    assert "window_seconds" in CONFIG_DEFAULTS
    assert "median_window_seconds" in CONFIG_DEFAULTS
    assert "peak_threshold_db" in CONFIG_DEFAULTS


def test_config_section_audio_resolves_via_clipper_config(isolated_cwd):
    from clipper.config import load_config

    (isolated_cwd / "config.toml").write_text(
        "[audio]\nsample_rate = 22050\n", encoding="utf-8"
    )

    config = load_config(isolated_cwd / "config.toml")

    section = config.section("audio")
    assert section["sample_rate"] == 22050
    assert section["window_seconds"] == 1.0
