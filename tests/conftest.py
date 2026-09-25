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
def fake_torch(monkeypatch):
    """Install a fake ``torch`` module in sys.modules so clipper.gpu can be
    tested against both CUDA-available and CUDA-unavailable cases without
    the real (heavy) torch dependency."""

    def _install(cuda_available: bool):
        module = types.ModuleType("torch")
        cuda_submodule = types.SimpleNamespace(is_available=lambda: cuda_available)
        module.cuda = cuda_submodule
        monkeypatch.setitem(sys.modules, "torch", module)
        return module

    return _install


@pytest.fixture
def no_torch(monkeypatch):
    """Ensure ``import torch`` raises ImportError, simulating an
    environment where torch isn't installed at all."""
    monkeypatch.setitem(sys.modules, "torch", None)
