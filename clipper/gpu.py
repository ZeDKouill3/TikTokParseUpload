from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Device:
    type: str  # "cuda" | "cpu"
    compute_type: str


_cuda_path_initialized = False


def ensure_cuda_dlls_on_path(site_packages: Path | str | None = None) -> None:
    """Ajoute au PATH du processus, et via ``os.add_dll_directory`` sous
    Windows, chaque dossier ``nvidia/<paquet>/bin`` present dans le
    site-packages courant (SPEC-38f7 R4) : sans eux, ctranslate2 ne voit pas
    le GPU et retombe sur CPU en silence (AGENTS.md, Pieges). Une seule fois
    par processus ; ``site_packages`` est injectable pour les tests."""
    global _cuda_path_initialized
    if _cuda_path_initialized:
        return
    _cuda_path_initialized = True

    root = Path(site_packages) if site_packages is not None else Path(sysconfig.get_path("purelib"))
    nvidia_dir = root / "nvidia"
    if not nvidia_dir.is_dir():
        return

    bin_dirs = [
        str(pkg_dir / "bin")
        for pkg_dir in sorted(nvidia_dir.iterdir())
        if (pkg_dir / "bin").is_dir()
    ]
    if not bin_dirs:
        return

    existing = os.environ.get("PATH", "")
    existing_entries = existing.split(os.pathsep) if existing else []
    new_dirs = [d for d in bin_dirs if d not in existing_entries]
    if new_dirs:
        os.environ["PATH"] = os.pathsep.join(new_dirs + existing_entries)

    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        for bin_dir in bin_dirs:
            os.add_dll_directory(bin_dir)


def get_device() -> Device:
    """Resolve the compute device (see ADR-fb9b): never hard-coded, always
    detected via ctranslate2, defaulting to CPU if ctranslate2 isn't
    installed, isn't able to report CUDA devices, or reports none."""
    ensure_cuda_dlls_on_path()
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
