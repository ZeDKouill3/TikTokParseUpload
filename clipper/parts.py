"""Etape parts : decoupage de chaque moment retenu en clip unique ou en
Part 1/2/.../N finissant chacune sur un suspense (SPEC-53f3, regle 3).

Entrees (workspace/<video_id>/) :
- moments.json (moments) : ``moments[].id, start, end, format, parts,
  hook_text, justification`` ; ``parts`` y est un decoupage indicatif,
  repris dans le prompt ;
- transcript.json (transcribe) : segments et mots horodates.

Sortie : workspace/<video_id>/parts.json

    {"video_id", "rubric": {"path", "durations"},
     "moments": [{"id", "start", "end", "duration", "format",
                  "parts_total", "proposed_cuts",
                  "parts": [{"part", "start", "end", "duration",
                             "hook_text", "suspense"}]}],
     "rejected": [{"id", "start", "end", "duration", "reason"}]}

Decision, bornes de [durations] dans rubric.toml, ``tolerance`` comprise
(la marge de recalage sur des frontieres de phrase) :
- duree dans single_min..single_max : clip unique, sans appel au LLM ;
- sinon N parties de part_min..part_max, N >= min_parts : clipper.llm
  (usage ``parts``) choisit les N-1 coupes, la ou une partie finit sur un
  suspense ; chaque coupe est recalee sur la fin de phrase la plus proche
  qui laisse toutes les parties dans les bornes (une coupe en fin de phrase
  n'est jamais dans un mot) ; la partie suivante commence a cette coupe,
  donc les parties couvrent le moment sans trou ni chevauchement ;
- aucun N possible, ou aucune suite de fins de phrase qui tienne les
  bornes : le moment va dans ``rejected`` avec la raison, jamais de
  decoupage de secours (ADR-ad2e).

Reponse LLM invalide ou Claude indisponible : l'erreur remonte, rien n'est
ecrit.
"""

from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clipper import llm

CONFIG_DEFAULTS: dict[str, object] = {
    # Grille (SPEC-53f3) dont [durations] fixe les bornes, relative au
    # dossier courant ; la meme que [moments] rubric_path.
    "rubric_path": "rubric.toml",
}

_DURATION_KEYS = ("single_min", "single_max", "part_min", "part_max", "min_parts", "tolerance")
_SENTENCE_END = (".", "!", "?", "…")
# Un moment est arrondi au dixieme (floor/ceil) autour de ses phrases.
_EDGE = 0.1
_EPS = 1e-6


class PartsError(Exception):
    """Entree manquante ou grille (rubric.toml) invalide."""


# --------------------------------------------------------------------------
# Grille
# --------------------------------------------------------------------------


def load_durations(path: str | Path) -> dict[str, float]:
    """Table [durations] de rubric.toml ; cle manquante ou mal typee :
    PartsError qui la nomme."""
    path = Path(path)
    if not path.exists():
        raise PartsError(f"grille introuvable : {path}")
    try:
        with path.open("rb") as f:
            rubric = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise PartsError(f"{path} : TOML invalide : {exc}") from exc
    durations = rubric.get("durations")
    if not isinstance(durations, dict):
        raise PartsError(f"{path} : table [durations] manquante")
    for key in _DURATION_KEYS:
        value = durations.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise PartsError(f"{path} : [durations] {key} manquant ou invalide")
    if durations["part_min"] - durations["tolerance"] <= 0:
        raise PartsError(f"{path} : [durations] part_min doit depasser tolerance")
    return {key: durations[key] for key in _DURATION_KEYS}


# --------------------------------------------------------------------------
# Phrases
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Sentence:
    start: float
    end: float
    text: str


def _ends_sentence(word: str) -> bool:
    return word.strip().rstrip("\"'»)]").endswith(_SENTENCE_END)


def split_sentences(transcript: dict[str, Any]) -> list[Sentence]:
    """Phrases de la transcription, decoupees comme l'etape moments : un mot
    finissant par . ! ? ou … ferme une phrase, une fin de segment aussi."""
    out: list[Sentence] = []

    def flush(words: list[dict[str, Any]]) -> None:
        text = "".join(w["word"] for w in words).strip()
        if text:
            out.append(Sentence(words[0]["start"], words[-1]["end"], text))

    for seg in transcript.get("segments", []):
        words = seg.get("words") or []
        if not words:
            if seg.get("text", "").strip():
                out.append(Sentence(seg["start"], seg["end"], seg["text"].strip()))
            continue
        current: list[dict[str, Any]] = []
        for word in words:
            current.append(word)
            if _ends_sentence(word["word"]):
                flush(current)
                current = []
        if current:
            flush(current)
    return out


def _inside(sents: list[Sentence], start: float, end: float) -> list[Sentence]:
    return [s for s in sents if s.start >= start - _EDGE - _EPS and s.end <= end + _EDGE + _EPS]


# --------------------------------------------------------------------------
# Decoupage
# --------------------------------------------------------------------------


def part_count_range(duration: float, d: dict[str, float]) -> tuple[int, int]:
    """Nombres de parties (min, max) qui peuvent tenir ``duration`` ;
    min > max si aucun."""
    low, high = d["part_min"] - d["tolerance"], d["part_max"] + d["tolerance"]
    return max(int(d["min_parts"]), math.ceil(duration / high - _EPS)), math.floor(duration / low + _EPS)


def snap_cuts(
    start: float, end: float, candidates: list[float], proposed: list[float], low: float, high: float
) -> list[float] | None:
    """Choisit len(proposed) coupes parmi ``candidates`` (fins de phrase,
    croissantes) telles que chaque partie dure entre ``low`` et ``high``, au
    plus pres des coupes proposees (somme des ecarts minimale) ; None si
    aucune suite ne tient les bornes."""
    fits = lambda a, b: low - _EPS <= b - a <= high + _EPS  # noqa: E731
    m = len(candidates)
    # cost[i], prev[j][i] : meilleure suite dont la j-ieme coupe est candidates[i].
    cost = [abs(c - proposed[0]) if fits(start, c) else math.inf for c in candidates]
    prev: list[list[int]] = [[-1] * m]
    for p in proposed[1:]:
        new, back = [math.inf] * m, [-1] * m
        for i, c in enumerate(candidates):
            for k in range(i):
                if cost[k] < new[i] and fits(candidates[k], c):
                    new[i], back[i] = cost[k], k
            new[i] += abs(c - p)
        cost = new
        prev.append(back)
    best = min(
        (i for i in range(m) if cost[i] < math.inf and fits(candidates[i], end)),
        key=lambda i: (cost[i], i),
        default=None,
    )
    if best is None:
        return None
    chosen = [best]
    for back in reversed(prev[1:]):
        chosen.append(back[chosen[-1]])
    return [candidates[i] for i in reversed(chosen)]


def response_schema(start: float, end: float, n_range: tuple[int, int]) -> dict[str, Any]:
    """Ce que le LLM renvoie pour un moment a couper en n_range parties."""
    return {
        "type": "object",
        "properties": {
            "cuts": {
                "type": "array",
                "minItems": n_range[0] - 1,
                "maxItems": n_range[1] - 1,
                "description": "Les coupes entre parties, dans l'ordre chronologique.",
                "items": {
                    "type": "object",
                    "properties": {
                        "at": {
                            "type": "number", "exclusiveMinimum": start, "exclusiveMaximum": end,
                            "description": "Instant de coupe en secondes : la fin d'une ligne de la transcription.",
                        },
                        "suspense": {
                            "type": "string", "minLength": 1, "maxLength": 400,
                            "description": "Pourquoi la partie qui finit ici laisse le spectateur en suspense.",
                        },
                    },
                    "required": ["at", "suspense"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["cuts"],
        "additionalProperties": False,
    }


def _fmt(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _prompt(moment: dict[str, Any], sents: list[Sentence], d: dict[str, float], n_range: tuple[int, int]) -> str:
    lines = "\n".join(f"[{_fmt(s.start)}-{_fmt(s.end)}] {s.text}" for s in sents)
    hint = ""
    if moment.get("parts"):
        spans = ", ".join(f"{_fmt(p['start'])}-{_fmt(p['end'])}" for p in moment["parts"])
        hint = f"Decoupage indicatif propose au tri des moments (a revoir librement) : {spans}\n"
    n_text = f"{n_range[0]}" if n_range[0] == n_range[1] else f"{n_range[0]} a {n_range[1]}"
    return (
        "Tu decoupes un moment d'une video longue en plusieurs parties pour TikTok "
        "(Part 1, Part 2, ...), publiees separement.\n\n"
        "## Regles\n"
        f"1. {n_text} parties, chacune de {_fmt(d['part_min'])} a {_fmt(d['part_max'])} s : "
        f"renvoie {n_range[0] - 1 if n_range[0] == n_range[1] else f'{n_range[0] - 1} a {n_range[1] - 1}'} coupe(s).\n"
        "2. Une coupe est la fin d'une ligne de la transcription : reprends son timecode de fin tel quel.\n"
        "3. Chaque partie sauf la derniere finit sur un suspense : question laissee ouverte, revelation "
        "imminente, conflit au sommet, phrase qui appelle la suite. Jamais au milieu d'une explication "
        "qui retombe, jamais apres la chute.\n"
        "4. La partie suivante repart sur une accroche : sa premiere ligne doit donner envie sans avoir "
        "vu la partie precedente.\n"
        "5. La derniere partie garde la chute du moment.\n\n"
        "## Moment\n"
        f"De {_fmt(moment['start'])} a {_fmt(moment['end'])} s ({_fmt(moment['end'] - moment['start'])} s).\n"
        f"Accroche : {moment.get('hook_text', '')}\n"
        f"Pourquoi il a ete retenu : {moment.get('justification', '')}\n"
        f"{hint}\n"
        "## Transcription du moment ([debut-fin] en secondes)\n"
        f"{lines}\n"
    )


def _part(n: int, start: float, end: float, sents: list[Sentence], suspense: str | None) -> dict[str, Any]:
    first = next(s for s in sents if s.start >= start - _EDGE - _EPS)
    return {
        "part": n,
        "start": start,
        "end": end,
        "duration": round(end - start, 2),
        "hook_text": first.text,
        "suspense": suspense,
    }


def _split(
    moment: dict[str, Any], sents: list[Sentence], d: dict[str, float], config: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """(decoupage, None) ou (None, raison du rejet)."""
    start, end = moment["start"], moment["end"]
    duration = end - start
    tol = d["tolerance"]
    record = {"id": moment["id"], "start": start, "end": end, "duration": round(duration, 2)}
    inside = _inside(sents, start, end)
    if not inside:
        return None, "aucune phrase de la transcription dans le moment"

    if d["single_min"] - tol - _EPS <= duration <= d["single_max"] + tol + _EPS:
        return {**record, "format": "single", "parts_total": 1, "proposed_cuts": [],
                "parts": [_part(1, start, end, inside, None)]}, None

    n_range = part_count_range(duration, d)
    if n_range[0] > n_range[1]:
        return None, (
            f"duree {duration:.1f} s : ni clip unique ({_fmt(d['single_min'])}-{_fmt(d['single_max'])} s) "
            f"ni {int(d['min_parts'])}+ parties de {_fmt(d['part_min'])}-{_fmt(d['part_max'])} s "
            f"(tolerance {_fmt(tol)} s)"
        )

    answer = llm.ask("parts", _prompt(moment, inside, d, n_range), [], response_schema(start, end, n_range),
                     config=config)
    proposals = sorted(answer["cuts"], key=lambda c: c["at"])
    candidates = [s.end for s in inside[:-1] if start + _EPS < s.end < end - _EPS]
    cut_times = snap_cuts(
        start, end, candidates, [c["at"] for c in proposals], d["part_min"] - tol, d["part_max"] + tol
    )
    if cut_times is None:
        return None, (
            f"aucune suite de fins de phrase ne donne {len(proposals) + 1} parties de "
            f"{_fmt(d['part_min'])}-{_fmt(d['part_max'])} s (tolerance {_fmt(tol)} s)"
        )
    edges = [start, *cut_times, end]
    suspense = [c["suspense"] for c in proposals] + [None]
    parts = [_part(n, a, b, inside, suspense[n - 1]) for n, (a, b) in enumerate(zip(edges, edges[1:]), 1)]
    return {**record, "format": "multipart", "parts_total": len(parts),
            "proposed_cuts": [c["at"] for c in proposals], "parts": parts}, None


# --------------------------------------------------------------------------
# Etape
# --------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise PartsError(f"entree absente : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _settings(config: Any) -> dict[str, Any]:
    if config is None:
        from clipper.config import load_config

        config = load_config()
    return {**CONFIG_DEFAULTS, **config.section("parts")}


def run(
    video_id: str,
    workspace_dir: str | Path = "workspace",
    *,
    config: Any = None,
    force: bool = False,
) -> Path:
    """Decoupe chaque moment de moments.json et ecrit
    workspace/<video_id>/parts.json, dont le chemin est renvoye. Un resultat
    deja present n'est pas refait, sauf ``force``."""
    video_dir = Path(workspace_dir) / video_id
    out = video_dir / "parts.json"
    if out.exists() and not force:
        return out

    moments = _read_json(video_dir / "moments.json")
    transcript = _read_json(video_dir / "transcript.json")
    settings = _settings(config)
    rubric_path = Path(settings["rubric_path"])
    durations = load_durations(rubric_path)
    sents = split_sentences(transcript)

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for moment in moments["moments"]:
        split, reason = _split(moment, sents, durations, config)
        if split is None:
            rejected.append({"id": moment["id"], "start": moment["start"], "end": moment["end"],
                             "duration": round(moment["end"] - moment["start"], 2), "reason": reason})
        else:
            kept.append(split)

    result = {
        "video_id": video_id,
        "rubric": {"path": str(rubric_path), "durations": durations},
        "moments": kept,
        "rejected": rejected,
    }
    video_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
