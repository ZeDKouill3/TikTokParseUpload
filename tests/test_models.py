"""TASK-c68fe39d5bcf : clipper/models.py (SPEC-38f7 R5). Jamais de reseau,
jamais de vrai modele : les fabriques sont toujours simulees."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipper.config import Config
from clipper.models import (
    DEFAULT_MEDIAPIPE_MODEL_PATH,
    DEFAULT_WHISPER_MODEL,
    ModelsError,
    mediapipe_model_path,
    prefetch,
    whisper_model_name,
)


def make_config(**sections) -> Config:
    return Config(mode="review", workspace_dir=Path("workspace"), output_dir=Path("output"), _sections=sections)


# --------------------------------------------------------------------------
# whisper_model_name / mediapipe_model_path : lecture brute, jamais
# clipper.transcribe/clipper.reframe importes.
# --------------------------------------------------------------------------


def test_whisper_model_name_defaults_without_config():
    assert whisper_model_name(None) == DEFAULT_WHISPER_MODEL == "small"


def test_whisper_model_name_defaults_when_section_absent():
    assert whisper_model_name(make_config()) == DEFAULT_WHISPER_MODEL


def test_whisper_model_name_reads_transcribe_section():
    config = make_config(transcribe={"model": "medium"})

    assert whisper_model_name(config) == "medium"


def test_mediapipe_model_path_defaults_without_config():
    assert mediapipe_model_path(None) == DEFAULT_MEDIAPIPE_MODEL_PATH


def test_mediapipe_model_path_reads_reframe_model_path_override():
    config = make_config(reframe={"model_path": "C:/models/face.tflite"})

    assert mediapipe_model_path(config) == Path("C:/models/face.tflite")


def test_mediapipe_model_path_blank_override_falls_back_to_default():
    config = make_config(reframe={"model_path": ""})

    assert mediapipe_model_path(config) == DEFAULT_MEDIAPIPE_MODEL_PATH


# --------------------------------------------------------------------------
# prefetch : fabriques simulees, jamais de reseau.
# --------------------------------------------------------------------------


class _FakeFactory:
    """Simule le contrat ``factory(local_files_only)`` : leve quand le
    modele n'est pas (encore) present pour ce mode, selon ``present_after``
    appels reussis en ``local_files_only=False``."""

    def __init__(self, *, already_present: bool, fails_download: bool = False):
        self.already_present = already_present
        self.fails_download = fails_download
        self.calls: list[bool] = []

    def __call__(self, *args: object) -> str:
        local_files_only = bool(args[-1])  # whisper_factory(name, ...) ou face_model_fetch(...)
        self.calls.append(local_files_only)
        if local_files_only:
            if self.already_present:
                return "cached"
            raise FileNotFoundError("not cached locally")
        if self.fails_download:
            raise RuntimeError("boom")
        return "downloaded"


def test_prefetch_calls_whisper_factory_with_the_configured_model_name():
    config = make_config(transcribe={"model": "medium"})
    calls: list[tuple[str, bool]] = []

    def whisper_factory(name: str, local_files_only: bool) -> str:
        calls.append((name, local_files_only))
        return "cached"

    prefetch(config, whisper_factory, lambda local_files_only: "cached")

    assert calls == [("medium", True)]


def test_prefetch_whisper_already_present_is_not_called_a_second_time():
    whisper = _FakeFactory(already_present=True)

    results = prefetch(make_config(), whisper, lambda local_files_only: "cached")

    assert whisper.calls == [True]  # jamais rappelee en local_files_only=False
    assert results[0].already_present is True


def test_prefetch_whisper_absent_is_called_again_to_download():
    whisper = _FakeFactory(already_present=False)

    results = prefetch(make_config(), whisper, lambda local_files_only: "cached")

    assert whisper.calls == [True, False]
    assert results[0].already_present is False


def test_prefetch_mediapipe_already_present_is_not_called_a_second_time():
    face = _FakeFactory(already_present=True)

    results = prefetch(make_config(), lambda name, local_files_only: "cached", face)

    assert face.calls == [True]
    assert results[1].already_present is True


def test_prefetch_mediapipe_absent_is_called_again_to_download():
    face = _FakeFactory(already_present=False)

    results = prefetch(make_config(), lambda name, local_files_only: "cached", face)

    assert face.calls == [True, False]
    assert results[1].already_present is False


def test_prefetch_whisper_download_failure_raises_models_error():
    whisper = _FakeFactory(already_present=False, fails_download=True)

    with pytest.raises(ModelsError, match="whisper:small"):
        prefetch(make_config(), whisper, lambda local_files_only: "cached")


def test_prefetch_mediapipe_download_failure_raises_models_error():
    face = _FakeFactory(already_present=False, fails_download=True)

    with pytest.raises(ModelsError, match="mediapipe"):
        prefetch(make_config(), lambda name, local_files_only: "cached", face)


def test_prefetch_reports_both_models_by_name():
    config = make_config(transcribe={"model": "small"})

    results = prefetch(
        config, lambda name, local_files_only: "cached", lambda local_files_only: "cached"
    )

    assert [r.name for r in results] == ["whisper:small", "mediapipe"]
    assert all(r.already_present for r in results)
