"""Etape vision : descriptions des images cles situees autour des moments
candidats, par clipper.llm (usage ``vision``, images fixes jointes, ADR-b1c1).

Entrees (workspace/<video_id>/) :
- moments.json (moments) : les candidats retenus (``moments``), et les
  rejetes (``rejected``) dont la grille (``rubric``) est reprise pour
  retrouver ceux qu'un bonus visuel pourrait faire remonter ;
- scenes.json (scenes) : images cles {"path", "timecode", "scene"}.

Sortie : workspace/<video_id>/vision.json

    {"video_id", "window_seconds",
     "frames": [{"timecode", "path", "description", "tags", "striking"}]}

Seules les images dont le timecode tombe dans la fenetre (``window_seconds``
de chaque cote) d'un moment retenu, ou d'un moment rejete pour score sous
min_score que le bonus visuel de rubric.toml (dans la limite de
[bonus].max_total) suffirait a faire remonter, partent au LLM : les autres
rejetes ne sont pas decrits. Les images sont reduites a ``max_width`` pixels
de large (proportions conservees) dans un dossier temporaire du workspace,
supprime en fin d'etape ; les originaux ne sont jamais modifies. Les lots
(``batch_size`` images chacun) sont traites jusqu'a ``parallel`` a la fois ;
chaque lot reussi est enregistre au fil de l'eau dans vision_partial.json
(ecriture atomique, verrou), relu au demarrage pour ne pas redemander un lot
deja decrit apres une relance.

L'etape moments, relancee par clipper.pipeline, lit ``frames`` (description
et ``striking``) et peut reviser ses notes. Reponse invalide ou LLM
indisponible : l'erreur remonte, rien n'est ecrit (ADR-ad2e).
"""

from __future__ import annotations

import json
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import cv2

from clipper import llm

CONFIG_DEFAULTS: dict[str, object] = {
    # Marge autour de chaque moment candidat, en secondes.
    "window_seconds": 10,
    # Images jointes par appel au LLM.
    "batch_size": 8,
    # Largeur max des images envoyees au LLM, proportions conservees.
    "max_width": 768,
    # Lots traites en meme temps (appels clipper.llm en sous-processus).
    "parallel": 4,
}


class VisionError(Exception):
    """Entree manquante, image cle introuvable ou grille (rubric.toml) invalide."""


def response_schema(n: int) -> dict[str, Any]:
    """Ce que le LLM renvoie pour un lot de ``n`` images."""
    return {
        "type": "object",
        "properties": {
            "frames": {
                "type": "array",
                "minItems": n,
                "maxItems": n,
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "minimum": 0, "maximum": n - 1},
                        "description": {
                            "type": "string", "minLength": 1, "maxLength": 300,
                            "description": "Ce qu'on voit, en une phrase concrete.",
                        },
                        "tags": {
                            "type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 8,
                            "description": "Mots-cles courts : personnes, action, lieu, texte a l'ecran.",
                        },
                        "striking": {
                            "type": "boolean",
                            "description": "true si l'image arrete le scroll a elle seule.",
                        },
                    },
                    "required": ["index", "description", "tags", "striking"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["frames"],
        "additionalProperties": False,
    }


def _prompt(batch: list[dict[str, Any]]) -> str:
    listing = "\n".join(f"Image {n} : {f['timecode']:.1f} s" for n, f in enumerate(batch))
    return (
        "Tu aides un monteur de clips verticaux courts (TikTok, Shorts, Reels) tires de videos "
        "longues. Voici des images cles extraites de la video, jointes dans cet ordre :\n"
        f"{listing}\n\n"
        "Pour chaque image (index = son numero) : une description concrete de ce qu'on voit "
        "(personnes, action, expression, texte a l'ecran), quelques tags, et striking = true "
        "seulement si l'image est visuellement marquante au point d'arreter le scroll "
        "(reaction extreme, action spectaculaire, revelation a l'ecran). Sois exigeant : "
        "une image ordinaire n'est pas marquante."
    )


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise VisionError(f"entree absente : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _bonus_settings(rubric_path: Path) -> tuple[float, float]:
    """(bonus.visual, bonus.max_total) lus dans rubric.toml, sans importer
    clipper.moments (ADR-b16b)."""
    if not rubric_path.exists():
        raise VisionError(f"grille introuvable : {rubric_path}")
    with rubric_path.open("rb") as f:
        rubric = tomllib.load(f)
    bonus = rubric.get("bonus")
    if not isinstance(bonus, dict):
        raise VisionError(f"{rubric_path} : table [bonus] manquante")
    for key in ("visual", "max_total"):
        if key not in bonus:
            raise VisionError(f"{rubric_path} : [bonus] {key} manquant")
    return float(bonus["visual"]), float(bonus["max_total"])


def _rescuable(rejected: list[dict[str, Any]], min_score: float, rubric_path: Path) -> list[dict[str, Any]]:
    """Rejets pour score sous min_score dont le score + le bonus visuel,
    plafonne a max_total, atteindrait min_score."""
    candidates = [r for r in rejected if "final_score" in r and isinstance(r.get("bonus"), dict)]
    candidates = [r for r in candidates if r["final_score"] < min_score]
    if not candidates:
        return []
    bonus_visual, max_total = _bonus_settings(rubric_path)
    out = []
    for r in candidates:
        room = max(0.0, max_total - float(r["bonus"].get("total", 0.0)))
        if r["final_score"] + min(bonus_visual, room) >= min_score:
            out.append(r)
    return out


def _windows(moments: dict[str, Any], margin: float) -> list[tuple[float, float]]:
    kept = moments.get("moments") or []
    rejected = moments.get("rejected") or []
    rubric_info = moments.get("rubric") or {}
    min_score = rubric_info.get("min_score")
    rescued: list[dict[str, Any]] = []
    if rejected and min_score is not None and rubric_info.get("path"):
        rescued = _rescuable(rejected, float(min_score), Path(rubric_info["path"]))
    return [
        (c["start"] - margin, c["end"] + margin)
        for c in kept + rescued
        if "start" in c and "end" in c
    ]


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    return {**CONFIG_DEFAULTS, **config.section("vision")}


def _resized_copy(path: Path, dest_dir: Path, max_width: int, index: int) -> Path:
    image = cv2.imread(str(path))
    if image is None:
        raise VisionError(f"image illisible : {path}")
    h, w = image.shape[:2]
    if w > max_width:
        image = cv2.resize(image, (max_width, max(1, round(h * max_width / w))))
    dest = dest_dir / f"{index:05d}_{Path(path).name}"
    if not cv2.imwrite(str(dest), image):
        raise VisionError(f"ecriture impossible : {dest}")
    return dest


def _load_partial(path: Path) -> dict[int, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in (data.get("batches") or {}).items()}


def _save_partial(path: Path, results: list[list[dict[str, Any]] | None]) -> None:
    batches = {str(n): r for n, r in enumerate(results) if r is not None}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"batches": batches}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run(
    video_id: str,
    workspace_dir: str | Path = "workspace",
    *,
    config: Any = None,
    force: bool = False,
) -> Path:
    """Decrit les images cles autour des moments candidats et ecrit
    workspace/<video_id>/vision.json, dont le chemin est renvoye. Un resultat
    deja present n'est pas refait, sauf ``force``."""
    video_dir = Path(workspace_dir) / video_id
    out = video_dir / "vision.json"
    if out.exists() and not force:
        return out

    moments = _read_json(video_dir / "moments.json")
    scenes = _read_json(video_dir / "scenes.json")
    settings = _settings(config)
    margin = float(settings["window_seconds"])
    batch_size = int(settings["batch_size"])
    max_width = int(settings["max_width"])
    parallel = int(settings["parallel"])
    if batch_size < 1:
        raise VisionError(f"[vision] batch_size doit etre >= 1 (recu {batch_size})")
    if max_width < 1:
        raise VisionError(f"[vision] max_width doit etre >= 1 (recu {max_width})")

    windows = _windows(moments, margin)
    selected = sorted(
        (f for f in scenes.get("frames") or [] if any(lo <= f["timecode"] <= hi for lo, hi in windows)),
        key=lambda f: f["timecode"],
    )
    for f in selected:
        if not (video_dir / f["path"]).is_file():
            raise VisionError(f"image cle introuvable : {video_dir / f['path']}")

    batches = [selected[first : first + batch_size] for first in range(0, len(selected), batch_size)]

    partial_path = video_dir / "vision_partial.json"
    done = _load_partial(partial_path)
    results: list[list[dict[str, Any]] | None] = [done.get(n) for n in range(len(batches))]
    lock = threading.Lock()

    def process(n: int) -> None:
        batch = batches[n]
        answer = llm.ask(
            "vision",
            _prompt(batch),
            [resized[f["path"]] for f in batch],
            response_schema(len(batch)),
            config=config,
        )
        indices = [item["index"] for item in answer["frames"]]
        if sorted(indices) != list(range(len(batch))):
            raise llm.SchemaError(f"vision : index attendus 0..{len(batch) - 1}, recus {indices}")
        described = [
            {
                "timecode": batch[item["index"]]["timecode"],
                "path": batch[item["index"]]["path"],
                "description": item["description"],
                "tags": item["tags"],
                "striking": item["striking"],
            }
            for item in sorted(answer["frames"], key=lambda item: item["index"])
        ]
        results[n] = described
        with lock:
            _save_partial(partial_path, results)

    resize_dir = video_dir / "vision_resize_tmp"
    resize_dir.mkdir(exist_ok=True)
    try:
        resized = {
            f["path"]: _resized_copy(video_dir / f["path"], resize_dir, max_width, n)
            for n, f in enumerate(selected)
        }
        pending = [n for n in range(len(batches)) if results[n] is None]
        if pending:
            with ThreadPoolExecutor(max_workers=max(1, parallel)) as executor:
                futures = [executor.submit(process, n) for n in pending]
                for future in futures:
                    future.result()
    finally:
        for f in resize_dir.iterdir():
            f.unlink()
        resize_dir.rmdir()

    described: list[dict[str, Any]] = [item for batch_result in results for item in (batch_result or [])]

    result = {"video_id": video_id, "window_seconds": margin, "frames": described}
    video_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    partial_path.unlink(missing_ok=True)
    return out
