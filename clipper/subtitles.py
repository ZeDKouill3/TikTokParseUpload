"""Etape subtitles : sous-titres style CapCut en .ass, karaoke mot par mot,
mots d'emphase choisis par clipper.llm (usage emphasis).

Entrees : workspace/<video_id>/transcript.json (etape transcribe) et
l'intervalle [start, end] du clip (secondes, relatif au debut de la video).
Sortie  : workspace/<video_id>/subtitles/<clip_id>.ass, timecodes relatifs
au debut du clip (start devient 0).

Le rendu (recadrage, position des visages) est decide par l'etape render :
cette etape ne detecte aucun visage, elle expose seulement une position
verticale parametrable (``avoid_zone``, une bande [haut, bas] en fraction de
la hauteur d'image 0..1 a ne pas recouvrir) que l'appelant fixe d'apres le
resultat de reframe (voir SPEC-350f : jamais de sous-titre sur un visage).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clipper import llm

PLAY_RES_X = 1080
PLAY_RES_Y = 1920

CONFIG_DEFAULTS: dict[str, object] = {
    "font_name": "Poppins ExtraBold",
    "font_size": 96,
    "outline": 6,
    "min_words_per_group": 2,
    "max_words_per_group": 4,
    # Distance (px) au bord ecran de la position par defaut (bas de l'image).
    "margin_v": 160,
    # Hauteur (px) reservee au texte pour decider si une avoid_zone la recouvre.
    "text_band_height": 260,
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


def _group_words(words: list[dict[str, Any]], min_size: int, max_size: int) -> list[list[dict[str, Any]]]:
    """Groupe les mots par lots de ``min_size`` a ``max_size``, sans jamais
    laisser un reliquat plus petit que ``min_size`` (sauf si l'intervalle
    entier en compte moins)."""
    groups: list[list[dict[str, Any]]] = []
    n = len(words)
    i = 0
    while i < n:
        remaining = n - i
        take = min(max_size, remaining)
        if 0 < remaining - take < min_size:
            take = remaining - min_size
        groups.append(words[i : i + take])
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


def _resolve_position(
    avoid_zone: tuple[float, float] | None, settings: dict[str, Any]
) -> tuple[int, int]:
    """(alignment, MarginV) pour la position par defaut (bas de l'image),
    deplacee en haut si ``avoid_zone`` (fraction 0..1 de la hauteur) recouvre
    la bande de texte par defaut."""
    margin_v = int(settings["margin_v"])
    band = int(settings["text_band_height"])
    if avoid_zone is None:
        return 2, margin_v  # bas, centre

    default_top = PLAY_RES_Y - margin_v - band
    default_bottom = PLAY_RES_Y - margin_v
    zone_top = avoid_zone[0] * PLAY_RES_Y
    zone_bottom = avoid_zone[1] * PLAY_RES_Y
    overlaps = zone_top < default_bottom and zone_bottom > default_top
    if not overlaps:
        return 2, margin_v
    return 8, margin_v  # haut, centre


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
        f"Default,,0,0,0,,{text}"
    )


def _render_ass(
    words: list[dict[str, Any]],
    clip_start: float,
    settings: dict[str, Any],
    emphasis: set[int],
    avoid_zone: tuple[float, float] | None,
) -> str:
    alignment, margin_v = _resolve_position(avoid_zone, settings)
    groups = _group_words(words, int(settings["min_words_per_group"]), int(settings["max_words_per_group"]))

    events = []
    offset = 0
    for group in groups:
        events.append(_dialogue_line(group, clip_start, emphasis, offset, settings))
        offset += len(group)

    style = (
        "Style: Default,{font},{size},{primary},{secondary},{outline_color},&H00000000,"
        "-1,0,0,0,100,100,0,0,1,{outline},0,{alignment},40,40,{margin_v},1"
    ).format(
        font=settings["font_name"],
        size=settings["font_size"],
        primary=settings["primary_color"],
        secondary=settings["secondary_color"],
        outline_color=settings["outline_color"],
        outline=settings["outline"],
        alignment=alignment,
        margin_v=margin_v,
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
    avoid_zone: tuple[float, float] | None = None,
) -> Path:
    """Genere workspace/<video_id>/subtitles/<clip_id>.ass pour [start, end]
    et renvoie ce chemin. Un .ass deja present n'est pas refait (ADR-b16b),
    sauf ``force``."""
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

    ass_text = _render_ass(words, start, settings, emphasis, avoid_zone)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".ass.tmp")
    tmp.write_text(ass_text, encoding="utf-8")
    tmp.replace(out)
    return out
