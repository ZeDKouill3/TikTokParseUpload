"""Etape captions : titre, legende, hashtags et texte d'accroche par clip
(SPEC-350f), demandes a clipper.llm (usage ``captions``) dans la langue de
la video.

Entrees (workspace/<video_id>/) :
- parts.json (parts) : chaque moment retenu, decoupe en un clip unique ou en
  Part 1/2/.../N (``id``, ``format``, ``parts_total``,
  ``parts``: [{"part","start","end","duration","hook_text","suspense"}]) ;
- moments.json (moments) : ``justification`` et accroche de selection de
  chaque moment retenu, par ``id`` ;
- transcript.json (transcribe) : ``language`` et les mots horodates, pour
  donner a l'IA le texte exact prononce dans chaque partie ;
- meta.json (download), facultatif : titre de la video, pour des hashtags
  plus pertinents.

Sortie : workspace/<video_id>/captions.json

    {"video_id",
     "clips": [{"id", "moment_id", "part", "parts_total", "start", "end",
                "duration", "language", "title", "caption", "hashtags",
                "hook_text"}]}

``id`` = ``<moment_id>`` sur 2 chiffres (clip unique) ou
``<moment_id>-p<part>`` (multipart), ex. ``03-p2`` (SPEC-350f).

Pour chaque clip, l'IA recoit le texte prononce dans la partie, l'accroche
et la justification du moment, et rend titre, legende, hashtags (chacun
commencant par #, sans doublon) et texte d'accroche (8 mots au plus, valeur
par defaut) dans la langue de la video ; ces regles sont revalidees ici, une
reponse qui les enfreint est traitee comme une reponse invalide. Reponse
invalide ou Claude indisponible : l'erreur remonte, rien n'est ecrit, aucune
legende de secours n'est inventee (ADR-ad2e).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clipper import llm

CONFIG_DEFAULTS: dict[str, object] = {
    "title_max_chars": 100,
    "caption_max_chars": 300,
    "hashtags_max": 8,
    "hook_words_max": 8,
}

_EDGE = 0.1
_EPS = 1e-6


class CaptionsError(Exception):
    """Entree manquante, ou parts.json et moments.json incoherents."""


# --------------------------------------------------------------------------
# Texte de la partie
# --------------------------------------------------------------------------


def _part_text(transcript: dict[str, Any], start: float, end: float) -> str:
    """Mots prononces dans [start, end] (bornes de la partie), dans l'ordre,
    tels qu'ecrits par l'etape transcribe."""
    words = [
        w
        for seg in transcript.get("segments", [])
        for w in (seg.get("words") or [])
        if w["start"] >= start - _EDGE - _EPS and w["end"] <= end + _EDGE + _EPS
    ]
    return "".join(w["word"] for w in words).strip()


# --------------------------------------------------------------------------
# Schema et prompt
# --------------------------------------------------------------------------


def response_schema(settings: dict[str, Any]) -> dict[str, Any]:
    """Ce que le LLM renvoie pour un clip."""
    return {
        "type": "object",
        "properties": {
            "title": {
                "type": "string", "minLength": 1, "maxLength": int(settings["title_max_chars"]),
                "description": "Titre accrocheur du clip, dans la langue de la video.",
            },
            "caption": {
                "type": "string", "minLength": 1, "maxLength": int(settings["caption_max_chars"]),
                "description": "Legende publiee sous le clip, dans la langue de la video.",
            },
            "hashtags": {
                "type": "array",
                "minItems": 1,
                "maxItems": int(settings["hashtags_max"]),
                "items": {
                    "type": "string", "minLength": 2, "maxLength": 30,
                    "description": "Un hashtag, en commencant par #.",
                },
                "description": "Hashtags pertinents pour ce clip precis, sans doublon.",
            },
            "hook_text": {
                "type": "string", "minLength": 1, "maxLength": 80,
                "description": (
                    f"Texte d'accroche affiche a l'ecran les 2 premieres secondes, "
                    f"{settings['hook_words_max']} mots au plus."
                ),
            },
        },
        "required": ["title", "caption", "hashtags", "hook_text"],
        "additionalProperties": False,
    }


def _prompt(
    language: str,
    video_title: str,
    moment: dict[str, Any],
    part: dict[str, Any],
    parts_total: int,
    text: str,
    settings: dict[str, Any],
) -> str:
    context = ""
    if parts_total > 1:
        context = (
            f"\nCe clip est la partie {part['part']}/{parts_total} d'une histoire plus longue : "
            "la legende peut le mentionner, mais l'accroche doit donner envie sans avoir vu les "
            "parties precedentes.\n"
        )
    return (
        "Tu ecris les metadonnees d'un clip vertical TikTok tire d'une video plus longue.\n\n"
        "## Regles\n"
        f"1. Reponds entierement dans la langue de la video ({language or 'celle de la transcription'}).\n"
        "2. title : court, accrocheur, sans hashtag ni exces d'emoji.\n"
        "3. caption : la legende publiee sous le clip, qui donne envie de regarder en entier.\n"
        "4. hashtags : chacun commence par #, jamais deux fois le meme, pertinents pour ce clip "
        f"precis (pas de generique inutile), {int(settings['hashtags_max'])} au plus.\n"
        f"5. hook_text : le texte affiche a l'ecran des le debut, {int(settings['hook_words_max'])} "
        "mots au plus, qui arrete le scroll.\n"
        f"{context}\n"
        "## Contexte\n"
        f"Video source : {video_title or '(sans titre)'}\n"
        f"Pourquoi ce moment a ete retenu : {moment.get('justification', '')}\n"
        f"Accroche du moment : {moment.get('hook_text', '')}\n\n"
        "## Texte prononce dans ce clip\n"
        f"{text}\n"
    )


# --------------------------------------------------------------------------
# Validation au-dela du schema
# --------------------------------------------------------------------------


def _validate_hashtags(hashtags: list[str]) -> None:
    seen: set[str] = set()
    for tag in hashtags:
        if not tag.startswith("#") or not tag[1:].strip():
            raise llm.SchemaError(f"hashtag invalide (doit commencer par #) : {tag!r}")
        key = tag.lower()
        if key in seen:
            raise llm.SchemaError(f"hashtag en double : {tag!r}")
        seen.add(key)


def _validate_hook_text(hook_text: str, max_words: int) -> None:
    n = len(hook_text.split())
    if n > max_words:
        raise llm.SchemaError(f"texte d'accroche de {n} mots, {max_words} au plus : {hook_text!r}")


# --------------------------------------------------------------------------
# Etape
# --------------------------------------------------------------------------


def _read_json(path: Path, optional: bool = False) -> Any:
    if not path.exists():
        if optional:
            return None
        raise CaptionsError(f"entree absente : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    return {**CONFIG_DEFAULTS, **config.section("captions")}


def _clip_id(moment_id: int, part: int, parts_total: int) -> str:
    base = f"{moment_id:02d}"
    return base if parts_total == 1 else f"{base}-p{part}"


def run(
    video_id: str,
    workspace_dir: str | Path = "workspace",
    *,
    config: Any = None,
    force: bool = False,
) -> Path:
    """Ecrit titre, legende, hashtags et texte d'accroche de chaque clip de
    parts.json dans workspace/<video_id>/captions.json, dont le chemin est
    renvoye. Un resultat deja present n'est pas refait, sauf ``force``."""
    video_dir = Path(workspace_dir) / video_id
    out = video_dir / "captions.json"
    if out.exists() and not force:
        return out

    parts_data = _read_json(video_dir / "parts.json")
    moments_data = _read_json(video_dir / "moments.json")
    transcript = _read_json(video_dir / "transcript.json")
    meta = _read_json(video_dir / "meta.json", optional=True) or {}
    settings = _settings(config)
    language = transcript.get("language") or ""
    video_title = meta.get("title") or ""
    moments_by_id = {m["id"]: m for m in moments_data["moments"]}
    schema = response_schema(settings)
    max_words = int(settings["hook_words_max"])

    clips: list[dict[str, Any]] = []
    for moment in parts_data["moments"]:
        source = moments_by_id.get(moment["id"])
        if source is None:
            raise CaptionsError(f"moment {moment['id']} de parts.json absent de moments.json")
        for part in moment["parts"]:
            text = _part_text(transcript, part["start"], part["end"])
            prompt = _prompt(language, video_title, source, part, moment["parts_total"], text, settings)
            answer = llm.ask("captions", prompt, [], schema, config=config)
            _validate_hashtags(answer["hashtags"])
            _validate_hook_text(answer["hook_text"], max_words)
            clips.append({
                "id": _clip_id(moment["id"], part["part"], moment["parts_total"]),
                "moment_id": moment["id"],
                "part": part["part"],
                "parts_total": moment["parts_total"],
                "start": part["start"],
                "end": part["end"],
                "duration": part["duration"],
                "language": language,
                "title": answer["title"],
                "caption": answer["caption"],
                "hashtags": answer["hashtags"],
                "hook_text": answer["hook_text"],
            })

    result = {"video_id": video_id, "clips": clips}
    video_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
