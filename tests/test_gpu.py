from __future__ import annotations


def test_get_device_returns_cpu_when_torch_is_not_installed(no_torch):
    from clipper.gpu import get_device

    device = get_device()

    assert device.type == "cpu"
    assert device.compute_type == "int8"


def test_get_device_returns_cuda_when_available(fake_torch):
    fake_torch(cuda_available=True)

    from clipper.gpu import get_device

    device = get_device()

    assert device.type == "cuda"
    assert device.compute_type == "float16"


def test_get_device_returns_cpu_when_cuda_unavailable(fake_torch):
    fake_torch(cuda_available=False)

    from clipper.gpu import get_device

    device = get_device()

    assert device.type == "cpu"
    assert device.compute_type == "int8"
