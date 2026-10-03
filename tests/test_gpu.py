from __future__ import annotations

import os
import sys

import pytest


def test_get_device_returns_cuda_when_cuda_device_count_positive(fake_ctranslate2):
    fake_ctranslate2(cuda_device_count=1)

    from clipper.gpu import get_device

    device = get_device()

    assert device.type == "cuda"
    assert device.compute_type == "float16"


def test_get_device_returns_cpu_when_cuda_device_count_zero(fake_ctranslate2):
    fake_ctranslate2(cuda_device_count=0)

    from clipper.gpu import get_device

    device = get_device()

    assert device.type == "cpu"
    assert device.compute_type == "int8"


def test_get_device_returns_cpu_when_ctranslate2_not_installed(no_ctranslate2):
    from clipper.gpu import get_device

    device = get_device()

    assert device.type == "cpu"
    assert device.compute_type == "int8"


def test_get_device_returns_cpu_when_ctranslate2_raises(fake_ctranslate2):
    fake_ctranslate2(raises=RuntimeError("no CUDA driver"))

    from clipper.gpu import get_device

    device = get_device()

    assert device.type == "cpu"
    assert device.compute_type == "int8"


# --- PATH des DLL nvidia (TASK-f6c495f901c0, SPEC-38f7 R4) ------------------


def test_ensure_cuda_dlls_on_path_adds_bin_dirs_at_head_in_order(tmp_path, monkeypatch):
    from clipper import gpu

    monkeypatch.setattr(gpu, "_cuda_path_initialized", False)
    cublas_bin = tmp_path / "nvidia" / "cublas" / "bin"
    cudnn_bin = tmp_path / "nvidia" / "cudnn" / "bin"
    cublas_bin.mkdir(parents=True)
    cudnn_bin.mkdir(parents=True)
    monkeypatch.setenv("PATH", "C:\\existant")

    gpu.ensure_cuda_dlls_on_path(tmp_path)

    entries = os.environ["PATH"].split(os.pathsep)
    assert entries[:2] == [str(cublas_bin), str(cudnn_bin)]
    assert entries[2:] == ["C:\\existant"]


def test_ensure_cuda_dlls_on_path_empty_tree_leaves_path_unchanged(tmp_path, monkeypatch):
    from clipper import gpu

    monkeypatch.setattr(gpu, "_cuda_path_initialized", False)
    monkeypatch.setenv("PATH", "C:\\existant")

    gpu.ensure_cuda_dlls_on_path(tmp_path)

    assert os.environ["PATH"] == "C:\\existant"


def test_ensure_cuda_dlls_on_path_no_duplicate_when_already_on_path(tmp_path, monkeypatch):
    from clipper import gpu

    bin_dir = tmp_path / "nvidia" / "cublas" / "bin"
    bin_dir.mkdir(parents=True)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}C:\\existant")
    monkeypatch.setattr(gpu, "_cuda_path_initialized", False)

    gpu.ensure_cuda_dlls_on_path(tmp_path)

    entries = os.environ["PATH"].split(os.pathsep)
    assert entries.count(str(bin_dir)) == 1


def test_ensure_cuda_dlls_on_path_runs_once_per_process(tmp_path, monkeypatch):
    from clipper import gpu

    monkeypatch.setattr(gpu, "_cuda_path_initialized", False)
    bin_dir = tmp_path / "nvidia" / "cublas" / "bin"
    bin_dir.mkdir(parents=True)
    monkeypatch.setenv("PATH", "C:\\existant")

    gpu.ensure_cuda_dlls_on_path(tmp_path)
    after_first = os.environ["PATH"]

    other_root = tmp_path / "autre"
    other_bin = other_root / "nvidia" / "cudnn" / "bin"
    other_bin.mkdir(parents=True)
    gpu.ensure_cuda_dlls_on_path(other_root)

    assert os.environ["PATH"] == after_first


@pytest.mark.skipif(sys.platform != "win32", reason="os.add_dll_directory est Windows seulement")
def test_ensure_cuda_dlls_on_path_registers_dll_directory_on_windows(tmp_path, monkeypatch):
    from clipper import gpu

    monkeypatch.setattr(gpu, "_cuda_path_initialized", False)
    bin_dir = tmp_path / "nvidia" / "cudnn" / "bin"
    bin_dir.mkdir(parents=True)
    monkeypatch.setenv("PATH", "")
    calls = []
    monkeypatch.setattr(gpu.os, "add_dll_directory", lambda p: calls.append(p), raising=False)

    gpu.ensure_cuda_dlls_on_path(tmp_path)

    assert calls == [str(bin_dir)]


def test_get_device_calls_ensure_cuda_dlls_on_path(fake_ctranslate2, monkeypatch):
    from clipper import gpu

    calls = []
    monkeypatch.setattr(gpu, "ensure_cuda_dlls_on_path", lambda *a, **k: calls.append(True))
    fake_ctranslate2(cuda_device_count=0)

    gpu.get_device()

    assert calls == [True]


# --- VRAM (TASK-dc9d) : jamais torch, toujours via clipper.gpu --------------


def _smi(monkeypatch, *, stdout="", returncode=0, error=None):
    import subprocess

    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if error is not None:
            raise error
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="boom")

    monkeypatch.setattr("clipper.gpu.subprocess.run", run)
    return calls


def test_vram_used_mb_reads_nvidia_smi_without_importing_torch(monkeypatch):
    import sys

    from clipper import gpu

    monkeypatch.setitem(sys.modules, "torch", None)  # un import torch leverait ImportError
    calls = _smi(monkeypatch, stdout="5120\n")

    assert gpu.vram_used_mb() == 5120
    assert calls[0][0] == "nvidia-smi" and "--query-gpu=memory.used" in calls[0]


def test_vram_used_mb_sums_every_gpu(monkeypatch):
    from clipper import gpu

    _smi(monkeypatch, stdout="1000\n2500\n")

    assert gpu.vram_used_mb() == 3500


def test_vram_used_mb_without_nvidia_smi_says_why(monkeypatch):
    import pytest

    from clipper import gpu

    _smi(monkeypatch, error=FileNotFoundError("nvidia-smi"))
    with pytest.raises(gpu.GpuError, match="nvidia-smi introuvable"):
        gpu.vram_used_mb()


def test_vram_used_mb_failure_or_garbage_output_is_an_explicit_error(monkeypatch):
    import pytest

    from clipper import gpu

    _smi(monkeypatch, returncode=9)
    with pytest.raises(gpu.GpuError, match="code 9"):
        gpu.vram_used_mb()
    _smi(monkeypatch, stdout="pas un nombre\n")
    with pytest.raises(gpu.GpuError, match="illisible"):
        gpu.vram_used_mb()
