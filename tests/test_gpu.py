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
