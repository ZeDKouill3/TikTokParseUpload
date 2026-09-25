"""Etape vision : descriptions des images cles situees autour des moments
candidats, par clipper.llm (usage ``vision``, images fixes jointes, ADR-b1c1).

Entrees (workspace/<video_id>/) :
- moments.json (moments) : les candidats, retenus (``moments``) comme
  rejetes (``rejected``) ; tous ont ete proposes et une image marquante peut
  faire remonter une note ;
- scenes.json (scenes) : images cles {"path", "timecode", "scene"}.

Sortie : workspace/<video_id>/vision.json

    {"video_id", "window_seconds",
     "frames": [{"timecode", "path", "description", "tags", "striking"}]}

Seules les images dont le timecode tombe dans un candidat elargi de
``window_seconds`` de chaque cote partent au LLM, par lots de ``batch_size``.
L'etape moments, relancee par clipper.pipeline, lit ``frames`` (description
et ``striking``) et peut reviser ses notes. Reponse invalide ou LLM
indisponible : l'erreur remonte, rien n'est ecrit (ADR-ad2e).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clipper import llm

CONFIG_DEFAULTS: dict[str, object] = {
    # Marge autour de chaque moment candidat, en secondes.
    "window_seconds": 10,
    # Images jointes par appel au LLM.
    "batch_size": 8,
}


class VisionError(Exception):
    """Entree manquante ou image cle introuvable."""


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


def _windows(moments: dict[str, Any], margin: float) -> list[tuple[float, float]]:
    return [
        (c["start"] - margin, c["end"] + margin)
        for c in (moments.get("moments") or []) + (moments.get("rejected") or [])
        if "start" in c and "end" in c
    ]


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    return {**CONFIG_DEFAULTS, **config.section("vision")}


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
    if batch_size < 1:
        raise VisionError(f"[vision] batch_size doit etre >= 1 (recu {batch_size})")

    windows = _windows(moments, margin)
    selected = sorted(
        (f for f in scenes.get("frames") or [] if any(lo <= f["timecode"] <= hi for lo, hi in windows)),
        key=lambda f: f["timecode"],
    )
    for f in selected:
        if not (video_dir / f["path"]).is_file():
            raise VisionError(f"image cle introuvable : {video_dir / f['path']}")

    described: list[dict[str, Any]] = []
    for first in range(0, len(selected), batch_size):
        batch = selected[first : first + batch_size]
        answer = llm.ask(
            "vision",
            _prompt(batch),
            [video_dir / f["path"] for f in batch],
            response_schema(len(batch)),
            config=config,
        )
        indices = [item["index"] for item in answer["frames"]]
        if sorted(indices) != list(range(len(batch))):
            raise llm.SchemaError(f"vision : index attendus 0..{len(batch) - 1}, recus {indices}")
        for item in sorted(answer["frames"], key=lambda item: item["index"]):
            f = batch[item["index"]]
            described.append(
                {
                    "timecode": f["timecode"],
                    "path": f["path"],
                    "description": item["description"],
                    "tags": item["tags"],
                    "striking": item["striking"],
                }
            )

    result = {"video_id": video_id, "window_seconds": margin, "frames": described}
    video_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
