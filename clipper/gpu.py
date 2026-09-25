from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    type: str  # "cuda" | "cpu"
    compute_type: str


def get_device() -> Device:
    """Resolve the compute device (see ADR-fb9b): never hard-coded, always
    detected via ctranslate2, defaulting to CPU if ctranslate2 isn't
    installed, isn't able to report CUDA devices, or reports none."""
    try:
        import ctranslate2

        cuda_device_count = ctranslate2.get_cuda_device_count()
    except Exception:
        return Device(type="cpu", compute_type="int8")

    if cuda_device_count > 0:
        return Device(type="cuda", compute_type="float16")
    return Device(type="cpu", compute_type="int8")
