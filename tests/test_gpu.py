from __future__ import annotations


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
