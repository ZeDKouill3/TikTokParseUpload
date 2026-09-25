"""Etape subtitles : sous-titres style CapCut en .ass, karaoke mot par mot,
mots d'emphase choisis par clipper.llm (usage emphasis).

Entrees : workspace/<video_id>/transcript.json (etape transcribe) et
l'intervalle [start, end] du clip (secondes, relatif au debut de la video).
Sortie  : workspace/<video_id>/subtitles/<clip_id>.ass, timecodes relatifs
au debut du clip (start devient 0).

Cette etape ne detecte aucun visage : l'appelant (clipper.pipeline) lui
donne, d'apres le plan de recadrage, les bandes a eviter plan par plan
(``avoid_zones`` : visages, SPEC-350f) et les bandes interdites
(``reserved_zones`` : l'accroche dessinee par render), au format
``[{"start", "end", "bands": [[haut, bas], ...]}]`` (temps en secondes de la
video, bandes en fraction 0..1 de la hauteur d'image).

Chaque evenement prend sa propre position (MarginV, texte aligne en bas),
choisie parmi des hauteurs candidates de la zone sure TikTok (``safe_zone`` :
hors de l'interface masquee en haut et en bas), de bas en haut, donc d'abord
dans le tiers inferieur de la zone : la premiere qui ne recouvre aucune bande
a eviter des plans ou il s'affiche. Sans position libre, la moins recouvrante
est prise et journalisee. Une bande interdite n'est jamais recouverte ; si
elle ne laisse aucune position, c'est une erreur.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from clipper import llm

PLAY_RES_X = 1080
PLAY_RES_Y = 1920

log = logging.getLogger(__name__)

# Debut d'un jeton colle au mot precedent par la transcription (elision,
# inversion) : " m" + "'a", " viens" + "-tu".
_GLUED_PREFIXES = ("'", "\u2019", "-")

CONFIG_DEFAULTS: dict[str, object] = {
    "font_name": "Poppins ExtraBold",
    "font_size": 96,
    "outline": 6,
    "min_words_per_group": 2,
    "max_words_per_group": 4,
    # Zone sure [haut, bas] (fraction de la hauteur) ou placer le texte :
    # l'interface TikTok masque le haut (~15 %) et le bas (~20 %).
    "safe_zone": [0.20, 0.78],
    # Ecart (px) entre deux hauteurs candidates, de bas en haut de la zone sure.
    "position_step": 16,
    # Hauteur (px) occupee par le texte (deux lignes et contour).
    "text_band_height": 260,
    "margin_left": 60,
    # Colonne des icones TikTok (j'aime, commentaires, partage) a droite.
    "margin_right": 150,
    "primary_color": "&H00FFFFFF&",   # blanc : mots deja prononces
    "secondary_color": "&H0080FFFF&", # jaune clair : mots pas encore prononces
    "outline_color": "&H00000000&",   # noir
    "emphasis_color": "&H0000A5FF&",  # orange : mots d'emphase
    "emphasis": True,
}

EMPHASIS_PROMPT = (
    "Voici les mots d'un extrait de sous-titres pour un clip vertical style "
    "CapCut, un mot par ligne precede de son index. Choisis les quelques "
    "mots a mettre en valeur (chiffres, mots forts, accroche) dans une "
    "couleur distincte. Ne liste que les index a mettre en valeur."
)


class SubtitlesError(Exception):
    """Transcription absente ou intervalle sans mot."""


def _emphasis_schema(n_words: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "indices": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": max(n_words - 1, 0)},
                "maxItems": n_words,
            },
        },
        "required": ["indices"],
        "additionalProperties": False,
    }


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    return {**CONFIG_DEFAULTS, **config.section("subtitles")}


def _words_in_interval(transcript: dict[str, Any], start: float, end: float) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for seg in transcript.get("segments", []):
        for w in seg.get("words", []):
            if w["start"] < end and w["end"] > start:
                words.append(w)
    words.sort(key=lambda w: w["start"])
    return words


def _ask_emphasis(words: list[dict[str, Any]], config: Any) -> set[int]:
    if not words:
        return set()
    lines = "\n".join(f"{i}\t{w['word'].strip()}" for i, w in enumerate(words))
    prompt = f"{EMPHASIS_PROMPT}\n\n{lines}"
    answer = llm.ask("emphasis", prompt, [], _emphasis_schema(len(words)), config=config)
    return set(answer["indices"])


def _units(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Mots au sens du regroupement : un jeton qui commence par une apostrophe
    ou un trait d'union colle ("'a", "-tu") reste avec le mot precedent."""
    units: list[list[dict[str, Any]]] = []
    for w in words:
        if units and w["word"].startswith(_GLUED_PREFIXES):
            units[-1].append(w)
        else:
            units.append([w])
    return units


def _group_words(words: list[dict[str, Any]], min_size: int, max_size: int) -> list[list[dict[str, Any]]]:
    """Groupe les mots par lots de ``min_size`` a ``max_size``, sans jamais
    laisser un reliquat plus petit que ``min_size`` (sauf si l'intervalle
    entier en compte moins). Un mot et ses jetons colles comptent pour un."""
    units = _units(words)
    groups: list[list[dict[str, Any]]] = []
    n = len(units)
    i = 0
    while i < n:
        remaining = n - i
        take = min(max_size, remaining)
        if 0 < remaining - take < min_size:
            take = remaining - min_size
        groups.append([w for unit in units[i : i + take] for w in unit])
        i += take
    return groups


def _format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    centis = round(seconds * 100)
    cs = centis % 100
    total_seconds = centis // 100
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _candidates(settings: dict[str, Any]) -> list[tuple[int, int]]:
    """Bandes [haut, bas] (px) ou poser le texte dans la zone sure, de bas en
    haut (le tiers inferieur de la zone d'abord)."""
    band = int(settings["text_band_height"])
    step = int(settings["position_step"])
    safe_top, safe_bottom = settings["safe_zone"]
    lowest = math.floor(float(safe_bottom) * PLAY_RES_Y)
    highest = math.ceil(float(safe_top) * PLAY_RES_Y) + band
    if lowest < highest:
        raise SubtitlesError(
            f"zone sure {settings['safe_zone']} trop petite pour {band} px de texte"
        )
    bottoms = list(range(lowest, highest - 1, -step))
    if bottoms[-1] != highest:
        bottoms.append(highest)
    return [(b - band, b) for b in bottoms]


def _bands_at(zones: list[dict[str, Any]], start: float, end: float) -> list[tuple[float, float]]:
    """Bandes (px) des zones dont l'intervalle de temps recoupe [start, end]."""
    return [
        (top * PLAY_RES_Y, bottom * PLAY_RES_Y)
        for z in zones
        if z["start"] < end and z["end"] > start
        for top, bottom in z["bands"]
    ]


def _covered(band: tuple[int, int], zones: list[tuple[float, float]]) -> float:
    """Hauteur (px) de ``band`` recouverte par l'union de ``zones``."""
    covered = 0.0
    reach = float(band[0])
    for top, bottom in sorted(zones):
        top, bottom = max(top, reach), min(bottom, band[1])
        if bottom > top:
            covered += bottom - top
            reach = bottom
    return covered


def _position(
    start: float,
    end: float,
    candidates: list[tuple[int, int]],
    avoid_zones: list[dict[str, Any]],
    reserved_zones: list[dict[str, Any]],
    where: str,
) -> tuple[int, int]:
    """Bande [haut, bas] (px) d'un evenement affiche de ``start`` a ``end``
    (secondes de la video)."""
    reserved = _bands_at(reserved_zones, start, end)
    allowed = [c for c in candidates if _covered(c, reserved) == 0]
    if not allowed:
        raise SubtitlesError(
            f"{where} {start:.2f}-{end:.2f}s : aucune position de la zone sure hors des "
            f"bandes reservees {reserved}"
        )
    faces = _bands_at(avoid_zones, start, end)
    best = min(allowed, key=lambda c: _covered(c, faces))  # le plus bas a egalite
    covered = _covered(best, faces)
    if covered > 0:
        log.warning(
            "subtitles %s %.2f-%.2fs : aucune position libre de visage, la moins "
            "recouvrante est prise (%d-%d px, %.0f px recouverts)",
            where, start, end, best[0], best[1], covered,
        )
    return best


def _karaoke_run(word: dict[str, Any], prev_end: float, emphasized: bool, settings: dict[str, Any]) -> str:
    gap_cs = round(max(0.0, word["start"] - prev_end) * 100)
    dur_cs = max(1, round((word["end"] - word["start"]) * 100))
    text = word["word"]
    prefix = f"{{\\k{gap_cs}}}" if gap_cs > 0 else ""
    if emphasized:
        return f"{prefix}{{\\k{dur_cs}\\c{settings['emphasis_color']}}}{text}{{\\r}}"
    return f"{prefix}{{\\k{dur_cs}}}{text}"


def _dialogue_line(
    group: list[dict[str, Any]],
    clip_start: float,
    emphasis: set[int],
    offset: int,
    settings: dict[str, Any],
    margin_v: int,
) -> str:
    start = group[0]["start"] - clip_start
    end = group[-1]["end"] - clip_start
    prev_end = group[0]["start"]
    runs = []
    for i, w in enumerate(group):
        runs.append(_karaoke_run(w, prev_end, (offset + i) in emphasis, settings))
        prev_end = w["end"]
    text = "".join(runs)
    return (
        f"Dialogue: 0,{_format_timestamp(start)},{_format_timestamp(end)},"
        f"Default,,0,0,{margin_v},,{text}"
    )


def _render_ass(
    words: list[dict[str, Any]],
    clip_start: float,
    settings: dict[str, Any],
    emphasis: set[int],
    avoid_zones: list[dict[str, Any]],
    reserved_zones: list[dict[str, Any]],
    where: str,
) -> str:
    candidates = _candidates(settings)
    groups = _group_words(words, int(settings["min_words_per_group"]), int(settings["max_words_per_group"]))

    events = []
    offset = 0
    for group in groups:
        _, bottom = _position(group[0]["start"], group[-1]["end"], candidates,
                              avoid_zones, reserved_zones, where)
        events.append(_dialogue_line(group, clip_start, emphasis, offset, settings, PLAY_RES_Y - bottom))
        offset += len(group)

    style = (
        "Style: Default,{font},{size},{primary},{secondary},{outline_color},&H00000000,"
        "-1,0,0,0,100,100,0,0,1,{outline},0,2,{margin_l},{margin_r},{margin_v},1"
    ).format(
        font=settings["font_name"],
        size=settings["font_size"],
        primary=settings["primary_color"],
        secondary=settings["secondary_color"],
        outline_color=settings["outline_color"],
        outline=settings["outline"],
        margin_l=settings["margin_left"],
        margin_r=settings["margin_right"],
        margin_v=PLAY_RES_Y - candidates[0][1],
    )

    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {PLAY_RES_X}\n"
        f"PlayResY: {PLAY_RES_Y}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(events)
        + ("\n" if events else "")
    )


def generate(
    video_id: str,
    clip_id: str,
    start: float,
    end: float,
    workspace_dir: str | Path = "workspace",
    *,
    config: Any = None,
    force: bool = False,
    avoid_zones: list[dict[str, Any]] | None = None,
    reserved_zones: list[dict[str, Any]] | None = None,
) -> Path:
    """Genere workspace/<video_id>/subtitles/<clip_id>.ass pour [start, end]
    et renvoie ce chemin. Un .ass deja present n'est pas refait (ADR-b16b),
    sauf ``force``. ``avoid_zones`` (visages) et ``reserved_zones``
    (accroche) : voir la docstring du module."""
    video_dir = Path(workspace_dir) / video_id
    out = video_dir / "subtitles" / f"{clip_id}.ass"
    if out.exists() and not force:
        return out

    transcript_file = video_dir / "transcript.json"
    if not transcript_file.exists():
        raise SubtitlesError(f"transcript.json absent : {transcript_file}")
    transcript = json.loads(transcript_file.read_text(encoding="utf-8"))

    settings = _settings(config)
    words = _words_in_interval(transcript, start, end)

    emphasis = _ask_emphasis(words, config) if settings["emphasis"] else set()

    ass_text = _render_ass(words, start, settings, emphasis, avoid_zones or [],
                           reserved_zones or [], f"{video_id}/{clip_id}")

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".ass.tmp")
    tmp.write_text(ass_text, encoding="utf-8")
    tmp.replace(out)
    return out
