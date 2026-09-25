from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    type: str  # "cuda" | "cpu"
    compute_type: str


def get_device() -> Device:
    """Resolve the compute device (see ADR-fb9b): never hard-coded, always
    detected from whatever torch reports, defaulting to CPU if torch itself
    isn't installed or CUDA isn't available."""
    try:
        import torch
    except ImportError:
        return Device(type="cpu", compute_type="int8")

    if torch.cuda.is_available():
        return Device(type="cuda", compute_type="float16")
    return Device(type="cpu", compute_type="int8")
