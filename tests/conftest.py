from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    """Run a test with cwd set to an empty temp dir, so config/workspace
    lookups never touch the real repo's config.toml or workspace/."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fake_ctranslate2(monkeypatch):
    """Install a fake ``ctranslate2`` module in sys.modules so clipper.gpu
    can be tested against CUDA-available, CUDA-unavailable and erroring
    cases without the real (heavy, GPU-requiring) dependency."""

    def _install(cuda_device_count=None, raises=None):
        module = types.ModuleType("ctranslate2")

        def _get_cuda_device_count():
            if raises is not None:
                raise raises
            return cuda_device_count

        module.get_cuda_device_count = _get_cuda_device_count
        monkeypatch.setitem(sys.modules, "ctranslate2", module)
        return module

    return _install


@pytest.fixture
def no_ctranslate2(monkeypatch):
    """Ensure ``import ctranslate2`` raises ImportError, simulating an
    environment where ctranslate2 isn't installed at all."""
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
