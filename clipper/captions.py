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
                "hook_text", "screen_title"}]}

``id`` = ``<moment_id>`` sur 2 chiffres (clip unique) ou
``<moment_id>-p<part>`` (multipart), ex. ``03-p2`` (SPEC-350f).

Pour chaque clip, l'IA recoit le texte prononce dans la partie, l'accroche
et la justification du moment, et rend titre, legende, hashtags (chacun
commencant par #, sans doublon), texte d'accroche (8 mots au plus, valeur
par defaut) et titre d'ecran ``screen_title`` (SPEC-6127, format letterbox :
6 mots au plus, valeur par defaut, et exactement un emoji simple) dans la
langue de la video ; ces regles sont revalidees ici et passees a llm.ask
comme controle : une reponse qui les enfreint est renvoyee au modele avec
l'erreur pour correction ([llm] repair_attempts), puis traitee comme une
reponse invalide si elle les enfreint encore. Reponse invalide ou Claude
indisponible : l'erreur remonte, rien n'est ecrit, aucune legende de secours
n'est inventee (ADR-ad2e).

Un moment multipart garde le meme screen_title dans toutes ses parties :
il est demande a l'IA une seule fois, avec la partie 1 (schema et prompt) ;
les parties suivantes ne le redemandent pas (le prompt cite celui deja
choisi comme contexte) et captions le recopie tel quel.
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
    "screen_title_words_max": 6,
}

_EDGE = 0.1
_EPS = 1e-6

# --------------------------------------------------------------------------
# screen_title : un seul emoji Extended_Pictographic (SPEC-6127).
# --------------------------------------------------------------------------

_ZWJ = "‍"
_VS16 = "️"
_SKIN_TONE_MODIFIERS = range(0x1F3FB, 0x1F400)
_REGIONAL_INDICATORS = range(0x1F1E6, 0x1F200)

# Approximation des plages Extended_Pictographic d'Unicode : les blocs
# d'emojis usuels, hors indicateurs regionaux (drapeaux, geres a part).
_PICTOGRAPHIC_RANGES = (
    (0x203C, 0x203C), (0x2049, 0x2049),
    (0x2122, 0x2122), (0x2139, 0x2139),
    (0x2194, 0x2199), (0x21A9, 0x21AA),
    (0x231A, 0x231B), (0x2328, 0x2328),
    (0x23CF, 0x23CF), (0x23E9, 0x23F3), (0x23F8, 0x23FA),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25AB), (0x25B6, 0x25B6), (0x25C0, 0x25C0), (0x25FB, 0x25FE),
    (0x2600, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B07), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55),
    (0x3030, 0x3030), (0x303D, 0x303D),
    (0x3297, 0x3297), (0x3299, 0x3299),
    (0x1F000, 0x1F0FF),
    (0x1F200, 0x1F2FF),
    (0x1F300, 0x1F5FF),
    (0x1F600, 0x1F64F),
    (0x1F680, 0x1F6FF),
    (0x1F700, 0x1F8FF),
    (0x1F900, 0x1F9FF),
    (0x1FA00, 0x1FAFF),
)


def _is_pictographic(codepoint: int) -> bool:
    return any(lo <= codepoint <= hi for lo, hi in _PICTOGRAPHIC_RANGES)


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


def response_schema(settings: dict[str, Any], *, include_screen_title: bool = True) -> dict[str, Any]:
    """Ce que le LLM renvoie pour un clip. ``include_screen_title`` est faux
    pour les parties d'un moment multipart apres la premiere : le titre
    d'ecran n'est alors plus redemande (recopie de la partie 1)."""
    properties: dict[str, Any] = {
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
    }
    required = ["title", "caption", "hashtags", "hook_text"]
    if include_screen_title:
        properties["screen_title"] = {
            "type": "string", "minLength": 1, "maxLength": 60,
            "description": (
                "Titre d'ecran affiche en haut, sur un encadre blanc, pendant tout le "
                f"clip : {settings['screen_title_words_max']} mots au plus (l'emoji ne "
                "compte pas) et exactement un emoji simple."
            ),
        }
        required.append("screen_title")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
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
    *,
    screen_title: str | None = None,
) -> str:
    context = ""
    if parts_total > 1:
        context = (
            f"\nCe clip est la partie {part['part']}/{parts_total} d'une histoire plus longue : "
            "la legende peut le mentionner, mais l'accroche doit donner envie sans avoir vu les "
            "parties precedentes.\n"
        )
    if screen_title is None:
        screen_title_rule = (
            f"6. screen_title : titre de 5-6 mots au plus ({int(settings['screen_title_words_max'])} "
            "au plus) affiche dans un encadre blanc au-dessus de la video, pendant tout le clip ; "
            "exactement un emoji simple (pas de sequence composee, pas de drapeau).\n"
        )
        screen_title_context = ""
    else:
        screen_title_rule = ""
        screen_title_context = (
            f"\nTitre d'ecran deja choisi pour ce moment, le meme dans toutes ses parties (ne pas "
            f"le redemander) : {screen_title}\n"
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
        f"{screen_title_rule}"
        f"{context}"
        f"{screen_title_context}\n"
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


def _count_words(text: str) -> int:
    return sum(1 for token in text.split() if any(c.isalnum() for c in token))


def _validate_hook_text(hook_text: str, max_words: int) -> None:
    n = _count_words(hook_text)
    if n > max_words:
        raise llm.SchemaError(f"texte d'accroche de {n} mots, {max_words} au plus : {hook_text!r}")


def _validate_screen_title_emoji(screen_title: str) -> None:
    """Exactement un emoji Extended_Pictographic, avec au plus un VS16 et un
    modificateur de teint ; sequence ZWJ et drapeau refuses (SPEC-6127)."""
    codepoints = [ord(c) for c in screen_title]
    n = len(codepoints)
    emoji_count = 0
    i = 0
    while i < n:
        cp = codepoints[i]
        if cp in _REGIONAL_INDICATORS and i + 1 < n and codepoints[i + 1] in _REGIONAL_INDICATORS:
            raise llm.SchemaError(f"emoji de type drapeau refuse dans screen_title : {screen_title!r}")
        if _is_pictographic(cp):
            j = i + 1
            if j < n and codepoints[j] == ord(_VS16):
                j += 1
            if j < n and codepoints[j] in _SKIN_TONE_MODIFIERS:
                j += 1
            if j < n and codepoints[j] == ord(_ZWJ):
                raise llm.SchemaError(
                    f"emoji compose (sequence ZWJ) refuse dans screen_title : {screen_title!r}"
                )
            emoji_count += 1
            i = j
            continue
        i += 1
    if emoji_count != 1:
        raise llm.SchemaError(
            f"screen_title doit contenir exactement un emoji, {emoji_count} trouve(s) : {screen_title!r}"
        )


def _validate_screen_title(screen_title: str, max_words: int) -> None:
    n = _count_words(screen_title)
    if n > max_words:
        raise llm.SchemaError(f"titre d'ecran de {n} mots, {max_words} au plus : {screen_title!r}")
    _validate_screen_title_emoji(screen_title)


def _check_answer(hook_words_max: int, screen_title_words_max: int, *, require_screen_title: bool = True):
    """Controle passe a llm.ask : ce qui le refuse est renvoye au modele
    pour correction, comme une reponse hors schema. ``require_screen_title``
    faux pour les parties d'un moment multipart apres la premiere : le
    schema ne demande alors plus ce champ."""

    def check(answer: dict[str, Any]) -> None:
        _validate_hashtags(answer["hashtags"])
        _validate_hook_text(answer["hook_text"], hook_words_max)
        if require_screen_title:
            _validate_screen_title(answer["screen_title"], screen_title_words_max)

    return check


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
    hook_words_max = int(settings["hook_words_max"])
    screen_title_words_max = int(settings["screen_title_words_max"])

    clips: list[dict[str, Any]] = []
    for moment in parts_data["moments"]:
        source = moments_by_id.get(moment["id"])
        if source is None:
            raise CaptionsError(f"moment {moment['id']} de parts.json absent de moments.json")
        screen_title: str | None = None
        for part in moment["parts"]:
            request_screen_title = screen_title is None
            schema = response_schema(settings, include_screen_title=request_screen_title)
            check = _check_answer(hook_words_max, screen_title_words_max,
                                   require_screen_title=request_screen_title)
            text = _part_text(transcript, part["start"], part["end"])
            prompt = _prompt(language, video_title, source, part, moment["parts_total"], text, settings,
                              screen_title=screen_title)
            answer = llm.ask("captions", prompt, [], schema, config=config, check=check)
            if request_screen_title:
                screen_title = answer["screen_title"]
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
                "screen_title": screen_title,
            })

    result = {"video_id": video_id, "clips": clips}
    video_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
