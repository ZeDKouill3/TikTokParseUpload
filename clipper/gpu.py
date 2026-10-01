from __future__ import annotations

import subprocess
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


class GpuError(Exception):
    """Mesure du GPU impossible (la raison est dans le message)."""


def vram_used_mb() -> int:
    """VRAM utilisee (Mo, tous les GPU NVIDIA cumules), lue par nvidia-smi :
    aucun import de torch (ADR-fb9b, un seul chemin pour interroger le GPU).
    ``GpuError`` explicite si nvidia-smi manque ou repond de travers."""
    cmd = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except FileNotFoundError as exc:
        raise GpuError("nvidia-smi introuvable dans le PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GpuError("nvidia-smi ne repond pas (10 s)") from exc
    if proc.returncode != 0:
        raise GpuError(f"nvidia-smi a echoue (code {proc.returncode}) : {(proc.stderr or '').strip()}")
    try:
        values = [int(line.strip()) for line in proc.stdout.splitlines() if line.strip()]
    except ValueError as exc:
        raise GpuError(f"sortie de nvidia-smi illisible : {proc.stdout.strip()!r}") from exc
    if not values:
        raise GpuError("nvidia-smi n'a signalé aucun GPU (sortie vide)")
    return sum(values)
