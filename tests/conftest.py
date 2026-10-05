from __future__ import annotations

import sys
import types

import cv2
import pytest

# OpenCV lance par defaut autant de threads internes (Sobel, cvtColor, resize,
# imread/imencode) que de coeurs logiques. Sous pytest-xdist, chaque worker
# fait la meme chose : N workers x jusqu'a cv2.getNumThreads() threads natifs
# sur une machine a 12 coeurs logiques sature largement le CPU, ce qui degrade
# le passage a l'echelle et starve l'ordonnancement des threads Python des
# tests bases sur le temps reel (ConcurrencyTracker). Un thread OpenCV par
# worker laisse la parallelisation reelle a pytest-xdist (process-level).
cv2.setNumThreads(1)


@pytest.fixture(autouse=True)
def _no_real_geolocation():
    """Aucun test ne lit le vrai service de géolocalisation (TASK-30cc) : la garde du navigateur piloté
    voit une IP française simulée. Les tests de clipper.network branchent leur propre lecture."""
    from clipper import network

    network.reset()
    network.use_fetcher(lambda url: {"ip": "192.0.2.1", "country": "FR", "city": "Test", "org": "test"})
    yield
    network.use_fetcher(None)
    network.reset()


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
