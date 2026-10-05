from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Purge (TASK-886a) : fichiers LOURDS d'un dossier workspace/<id>/, refaisables par une etape ;
# tout le reste (pipeline.json, meta.json, transcription, moments, captions, vignettes, plans de
# recadrage, sous-titres...) sert a l'affichage et reste.
SOURCE_SUFFIX = ".mp4"  # la video source telechargee : <id>.mp4
HEAVY_FILES = ("transcribe_audio.wav",)
HEAVY_DIRS = ("frames", "qa", "vision_resize_tmp", "render")
PURGE_MARKER = "purged.json"
# Publications qu'un clip de output/ attend encore (publish.UNFINISHED_STATUSES, sans importer d'etape).
_BLOCKING_STATUSES = ("approved", "scheduled", "failed")
_BUSY_STATUSES = ("running", "queued")


class PurgeRefused(Exception):
    """Purge impossible en l'etat (message francais, nomme la cause)."""


class Workspace:
    """Per-video working directory: workspace/<video_id>/<step>/result.json.

    Presence of a step's result is what "done" means: crash recovery and
    anti-duplicate work come from checking the filesystem, not from a
    separate ledger (see ADR-b16b).
    """

    def __init__(self, video_id: str, root: str | Path = "workspace"):
        self.video_id = video_id
        self.root = Path(root)
        self.dir = self.root / video_id

    def step_output(self, step: str) -> Path:
        return self.dir / step / "result.json"

    def is_done(self, step: str) -> bool:
        return self.step_output(step).exists()

    def mark_done(self, step: str, data: dict | None = None) -> Path:
        path = self.step_output(step)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data if data is not None else {}))
        return path

    def should_run(self, step: str, force: bool = False) -> bool:
        return force or not self.is_done(step)



# --------------------------------------------------------------------------
# Purge des fichiers lourds (TASK-886a)
# --------------------------------------------------------------------------


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return 0


def disk_usage(workspace_root: str | Path, output_root: str | Path) -> dict[str, int]:
    return {"workspace_bytes": _size(Path(workspace_root)), "output_bytes": _size(Path(output_root))}


def heavy_paths(video_id: str, root: str | Path = "workspace") -> list[Path]:
    video_dir = Path(root) / video_id
    candidates = [video_dir / f"{video_id}{SOURCE_SUFFIX}", *(video_dir / n for n in HEAVY_FILES),
                  *(video_dir / n for n in HEAVY_DIRS)]
    return [p for p in candidates if p.exists()]


def heavy_size(video_id: str, root: str | Path = "workspace") -> int:
    return sum(_size(p) for p in heavy_paths(video_id, root))


def is_purged(video_id: str, root: str | Path = "workspace") -> bool:
    """Vrai tant que la source a ete purgee et n'est pas revenue (retelechargee)."""
    video_dir = Path(root) / video_id
    return (video_dir / PURGE_MARKER).is_file() and not (video_dir / f"{video_id}{SOURCE_SUFFIX}").exists()


def _read_list(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PurgeRefused(f"fichier illisible ({path.name}) : {exc}") from exc
    if not isinstance(data, list):
        raise PurgeRefused(f"fichier illisible ({path.name}) : une liste est attendue")
    return data


def busy_reason(video_id: str, root: str | Path, queue_path: str | Path | None) -> str | None:
    """Pourquoi la video est en traitement ou en file (None si elle ne l'est pas)."""
    state_file = Path(root) / video_id / "pipeline.json"
    if state_file.is_file():
        try:
            status = json.loads(state_file.read_text(encoding="utf-8")).get("status")
        except (OSError, ValueError) as exc:
            raise PurgeRefused(f"{video_id} : pipeline.json illisible : {exc}") from exc
        if status in _BUSY_STATUSES:
            return f"{video_id} est en cours de traitement ({status})"
    if queue_path is not None and Path(queue_path).is_file():
        if any(isinstance(e, dict) and e.get("video_id") == video_id for e in _read_list(Path(queue_path))):
            return f"{video_id} est dans la file de traitement"
    return None


def purge_heavy(video_id: str, root: str | Path = "workspace", *, queue_path: str | Path | None = None) -> int:
    """Supprime les fichiers lourds de workspace/<video_id>/ ; renvoie les octets liberes."""
    video_dir = Path(root) / video_id
    if not video_dir.is_dir():
        raise PurgeRefused(f"dossier de la video introuvable : {video_dir}")
    reason = busy_reason(video_id, root, queue_path)
    if reason:
        raise PurgeRefused(f"purge refusee : {reason}")
    freed = 0
    for path in heavy_paths(video_id, root):
        freed += _size(path)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    (video_dir / PURGE_MARKER).write_text(
        json.dumps({"purged_at": datetime.now(timezone.utc).isoformat(), "freed_bytes": freed}), encoding="utf-8")
    log.info("purge de %s : %d octets liberes", video_id, freed)
    return freed


def _blocking_publications(video_id: str, publish_dir: str | Path | None) -> list[str]:
    names: list[str] = []
    if publish_dir is None or not Path(publish_dir).is_dir():
        return names
    for path in sorted(Path(publish_dir).glob("*.json")):
        for entry in _read_list(path):
            if not isinstance(entry, dict) or entry.get("video_id") != video_id:
                continue
            if entry.get("status") in _BLOCKING_STATUSES or entry.get("in_progress_since"):
                names.append(str(entry.get("clip_id")))
    return names


def clips_size(video_id: str, output_root: str | Path = "output") -> int:
    return _size(Path(output_root) / video_id)


def check_clips_purgeable(video_id: str, publish_dir: str | Path | None) -> None:
    blocking = _blocking_publications(video_id, publish_dir)
    if blocking:
        raise PurgeRefused(
            f"clips de {video_id} gardes : le clip {blocking[0]} a une publication programmee, en cours ou en attente"
            + (f" (et {len(blocking) - 1} autre(s))" if len(blocking) > 1 else ""))


def purge_clips(video_id: str, output_root: str | Path = "output", publish_dir: str | Path | None = None) -> int:
    """Supprime output/<video_id>/ ; refuse si un clip a une publication programmee, en cours ou en attente."""
    check_clips_purgeable(video_id, publish_dir)
    out = Path(output_root) / video_id
    freed = _size(out)
    if out.is_dir():
        shutil.rmtree(out)
    log.info("purge des clips de %s : %d octets liberes", video_id, freed)
    return freed
