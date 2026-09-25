"""Etape moments : choix des meilleurs moments d'une video longue par
clipper.llm (usage ``moments``), selon la grille de SPEC-53f3 (rubric.toml).

Entrees (workspace/<video_id>/) :
- meta.json (download) : titre, chapitres, heatmap, segments SponsorBlock ;
- transcript.json (transcribe) : segments et mots horodates ;
- audio.json (audio) : pics d'energie ;
- vision.json (vision), facultatif :
  {"frames": [{"timecode", "description", "striking": bool}]} ;
- ``examples`` : decisions humaines journalisees (feedback.examples), passees
  par clipper.pipeline, une etape n'important jamais une autre (ADR-b16b).

Sortie : workspace/<video_id>/moments.json

    {"video_id", "rubric": {"path", "weights", "min_score"}, "chunked",
     "selection": "single" | "jury",
     "jury": {"judges", "seed", "threshold", "quorum", "failed", "debated"},  # jury
     "exploration": {"share", "seed", "target", "chosen"},   # jury, part > 0
     "moments": [{"id", "start", "end", "duration", "format", "parts",
                  "scores", "bonus", "final_score", "justification",
                  "hook_text", "jury", "exploration"}],       # jury : si jury ;
                                                             # exploration : true
     "rejected": [{"start", "end", "reason", ...}],
     "rescored": {"source", "changed": [{"id", "start", "end", "hook_text",
                                          "before", "after"}]}}   # re-notation

Selection par le jury (ADR-ff87), en mode auto ou si [moments] selection =
"jury" : l'appel ``moments`` ne sert qu'a proposer une liste large de
candidats ; clipper.jury les note ensuite sur la meme grille, et ses notes
agregees (``scores``) remplacent celles du proposeur dans le score final
(bonus, ``min_score`` et non-chevauchement inchanges). ``jury`` de chaque
candidat garde les notes et la justification du proposeur, le score du jury,
son veto et sa trace (tours, revisions, dissidences). Un veto rejette le
candidat avec sa raison, sans score final. Juge invalide : l'erreur remonte,
rien n'est ecrit (ADR-ad2e).

Exploration (ADR-1cf0, point 4), en selection par jury : en plus des retenus,
``exploration_share`` x leur nombre (arrondi au plus proche) clips sont pris
parmi les candidats notes non retenus ou le jury hesite le plus, pour
apprendre ce qu'il sous-estime. Dispersion d'un candidat = ecart entre le
score le plus haut et le plus bas des juges, chacun a son dernier tour
(``jury.trace.rounds``) ; egalites departagees par un tirage a graine fixe
(``exploration_seed``). Jamais un candidat vete ni rejete par la grille
(SponsorBlock, duree), jamais un chevauchement avec un retenu ou un autre
clip d'exploration. Ces clips portent ``exploration: true`` ; le bloc
``exploration`` dit combien etaient vises (``target``) et pris (``chosen``).
Part 0 : aucune exploration, sortie inchangee.

Re-notation : si moments.json existe et que vision.json est plus recent,
l'etape (sans ``force``) ne rappelle pas le LLM ; elle recalcule le bonus
visuel, le score final, ``min_score`` et le non-chevauchement sur les
candidats deja notes, et liste dans ``rescored.changed`` ceux dont le score
ou le sort (retenu ou non) a change.

Le LLM ne fait que proposer des bornes et noter chaque critere de 0 a 10 ;
tout le reste est fait ici, de facon verifiable :
1. bornes recalees sur les frontieres de phrase les plus proches (debut du
   premier mot, fin du dernier : ni mot coupe ni silence en bord) ;
2. rejet des moments qui chevauchent un segment SponsorBlock exclu ou dont
   la duree sort des bornes de la grille ;
3. score final = moyenne ponderee des notes x10 + bonus plafonne des signaux
   mesures (most replayed, pics audio, images marquantes) ;
4. rejet sous ``min_score``, puis, entre moments qui se chevauchent, seul le
   mieux note reste. Aucun plafond sur le nombre de moments.

Transcription trop longue pour un appel (``max_transcript_chars``) : tranches
avec recouvrement, puis un tour de comparaison final qui re-note ensemble
tous les candidats, pour que les notes de tranches differentes soient
comparables (sauf avec le jury, qui note deja tous les candidats ensemble).
Reponse invalide ou Claude indisponible : l'erreur remonte, rien
n'est ecrit (ADR-ad2e).
"""

from __future__ import annotations

import json
import math
import random
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clipper import jury, llm

CONFIG_DEFAULTS: dict[str, object] = {
    # Qui note les candidats du proposeur : "single" (le proposeur seul) ou
    # "jury" (clipper.jury, ADR-ff87). En mode auto, le jury note toujours.
    "selection": "single",
    # Grille de notation (SPEC-53f3), relative au dossier courant.
    "rubric_path": "rubric.toml",
    # Au-dela, la transcription part en tranches (environ 4 caracteres par
    # token : 400 000 caracteres ~ 100k tokens).
    "max_transcript_chars": 400_000,
    "chunk_chars": 250_000,
    # Recouvrement entre deux tranches : une histoire a cheval reste entiere
    # dans au moins une tranche.
    "chunk_overlap_seconds": 300,
    # Pics audio envoyes au LLM (les plus forts).
    "max_audio_peaks": 200,
    # Selection par jury : part des clips retenus ajoutee en exploration,
    # prise parmi les candidats ou le jury hesite (ADR-1cf0). 0 : aucune.
    "exploration_share": 0.1,
    # Graine du tirage qui departage les candidats de meme dispersion.
    "exploration_seed": 0,
}

FORMATS = ("single", "multipart")
SELECTIONS = ("single", "jury")
_SENTENCE_END = (".", "!", "?", "…")
_EXAMPLE_TEXT_CHARS = 600


class MomentsError(Exception):
    """Entree manquante ou grille (rubric.toml) invalide."""


# --------------------------------------------------------------------------
# Grille
# --------------------------------------------------------------------------

_DURATION_KEYS = ("single_min", "single_max", "part_min", "part_max", "min_parts", "tolerance")
_BONUS_KEYS = ("max_total", "replayed", "audio_peaks", "audio_peaks_full", "visual")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_rubric(path: str | Path) -> dict[str, Any]:
    """Lit et valide rubric.toml ; toute cle manquante ou mal typee est une
    MomentsError qui la nomme."""
    path = Path(path)
    if not path.exists():
        raise MomentsError(f"grille introuvable : {path}")
    try:
        with path.open("rb") as f:
            rubric = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise MomentsError(f"{path} : TOML invalide : {exc}") from exc

    criteria = rubric.get("criteria")
    if not isinstance(criteria, dict) or not criteria:
        raise MomentsError(f"{path} : aucune table [criteria.<nom>]")
    for name, c in criteria.items():
        if not isinstance(c, dict) or not _number(c.get("weight")) or c["weight"] < 0:
            raise MomentsError(f"{path} : [criteria.{name}] weight manquant ou invalide")
        if not isinstance(c.get("question"), str) or not c["question"].strip():
            raise MomentsError(f"{path} : [criteria.{name}] question manquante")
    if sum(c["weight"] for c in criteria.values()) <= 0:
        raise MomentsError(f"{path} : la somme des poids doit etre positive")
    if not _number(rubric.get("min_score")):
        raise MomentsError(f"{path} : min_score manquant ou invalide")
    keywords = rubric.get("trend_keywords")
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        raise MomentsError(f"{path} : trend_keywords doit etre une liste de chaines")
    for table, keys in (("durations", _DURATION_KEYS), ("bonus", _BONUS_KEYS)):
        values = rubric.get(table)
        if not isinstance(values, dict):
            raise MomentsError(f"{path} : table [{table}] manquante")
        for key in keys:
            if not _number(values.get(key)):
                raise MomentsError(f"{path} : [{table}] {key} manquant ou invalide")
    categories = rubric.get("exclusions", {}).get("sponsorblock_categories")
    if not isinstance(categories, list):
        raise MomentsError(f"{path} : [exclusions] sponsorblock_categories manquant")
    return rubric


# --------------------------------------------------------------------------
# Phrases et timecodes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Sentence:
    start: float
    end: float
    text: str


def _floor1(x: float) -> float:
    return math.floor(x * 10 + 1e-6) / 10


def _ceil1(x: float) -> float:
    return math.ceil(x * 10 - 1e-6) / 10


def _span(start: float, end: float) -> str:
    return f"{_floor1(start):.1f}-{_ceil1(end):.1f}"


def _ends_sentence(word: str) -> bool:
    return word.strip().rstrip("\"'»)]").endswith(_SENTENCE_END)


def split_sentences(transcript: dict[str, Any]) -> list[Sentence]:
    """Phrases de la transcription : un mot finissant par . ! ? ou … ferme
    une phrase, une fin de segment aussi (pause detectee par whisper)."""
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


def _line(s: Sentence) -> str:
    return f"[{_span(s.start, s.end)}] {s.text}"


def _chunks(sents: list[Sentence], chunk_chars: int, overlap: float) -> list[list[Sentence]]:
    """Tranches d'environ ``chunk_chars`` caracteres ; chaque tranche reprend
    les ``overlap`` dernieres secondes de la precedente."""
    chunks: list[list[Sentence]] = []
    first = 0
    while first < len(sents):
        size, last = 0, first
        while last < len(sents) and (last == first or size + len(_line(sents[last])) + 1 <= chunk_chars):
            size += len(_line(sents[last])) + 1
            last += 1
        chunks.append(sents[first:last])
        if last >= len(sents):
            break
        cut = sents[last - 1].end - overlap
        nxt = next((k for k in range(first + 1, last) if sents[k].start >= cut), last)
        first = max(nxt, first + 1)
    return chunks


# --------------------------------------------------------------------------
# Prompt et schema de reponse
# --------------------------------------------------------------------------


def _scores_schema(rubric: dict[str, Any]) -> dict[str, Any]:
    criteria = rubric["criteria"]
    return {
        "type": "object",
        "description": "Note entiere de 0 a 10 par critere de la grille.",
        "properties": {
            name: {"type": "integer", "minimum": 0, "maximum": 10, "description": c["question"]}
            for name, c in criteria.items()
        },
        "required": list(criteria),
        "additionalProperties": False,
    }


def response_schema(rubric: dict[str, Any]) -> dict[str, Any]:
    """Ce que le LLM renvoie pour une transcription (ou une tranche)."""
    return {
        "type": "object",
        "properties": {
            "moments": {
                "type": "array",
                "description": "Tous les moments candidats, dans l'ordre chronologique.",
                "items": {
                    "type": "object",
                    "properties": {
                        "hook_text": {
                            "type": "string", "minLength": 1, "maxLength": 400,
                            "description": "La phrase d'accroche qui ouvre le clip, recopiee de la transcription.",
                        },
                        "start": {
                            "type": "number", "minimum": 0,
                            "description": "Debut en secondes : le debut de la ligne qui porte l'accroche.",
                        },
                        "end": {
                            "type": "number", "exclusiveMinimum": 0,
                            "description": "Fin en secondes : la fin d'une ligne, apres la chute.",
                        },
                        "format": {
                            "type": "string", "enum": list(FORMATS),
                            "description": "single : un clip court ; multipart : histoire longue en plusieurs parties.",
                        },
                        "part_breaks": {
                            "type": "array", "items": {"type": "number", "minimum": 0},
                            "description": "multipart : instants de coupe entre parties (fin d'une ligne) ; [] pour single.",
                        },
                        "justification": {
                            "type": "string", "minLength": 1, "maxLength": 500,
                            "description": "Une ou deux phrases : pourquoi ce moment marche en clip, ou ce qui le limite.",
                        },
                        "scores": _scores_schema(rubric),
                    },
                    "required": ["hook_text", "start", "end", "format", "part_breaks", "justification", "scores"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["moments"],
        "additionalProperties": False,
    }


def comparison_schema(rubric: dict[str, Any], n: int) -> dict[str, Any]:
    """Ce que le LLM renvoie au tour de comparaison : une nouvelle note pour
    chacun des ``n`` candidats, par id."""
    return {
        "type": "object",
        "properties": {
            "moments": {
                "type": "array",
                "minItems": n,
                "maxItems": n,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "minimum": 0, "maximum": n - 1},
                        "justification": {"type": "string", "minLength": 1, "maxLength": 500},
                        "scores": _scores_schema(rubric),
                    },
                    "required": ["id", "justification", "scores"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["moments"],
        "additionalProperties": False,
    }


def _grid_text(rubric: dict[str, Any]) -> str:
    d = rubric["durations"]
    criteria = "\n".join(f"- {name} : {c['question']}" for name, c in rubric["criteria"].items())
    keywords = ", ".join(rubric["trend_keywords"]) or "(aucun)"
    return (
        "## Grille : une note entiere de 0 a 10 par critere\n"
        f"{criteria}\n"
        f"Mots-cles tendance (critere trend) : {keywords}\n\n"
        "Echelle : 0-2 absent, 3-4 faible, 5-6 correct, 7-8 fort, 9-10 exceptionnel (rare). "
        "Note chaque critere independamment et sans complaisance : le score final est calcule "
        "par le programme a partir de tes notes et les moments faibles sont elimines "
        "automatiquement ; une note gonflee fait publier un mauvais clip.\n\n"
        "## Regles de decoupe\n"
        "1. Le clip commence sur l'accroche (la phrase qui arrete le scroll), jamais sur la mise "
        "en contexte. start = debut d'une ligne de la transcription, end = fin d'une ligne : "
        "reprends les timecodes des lignes tels quels.\n"
        f"2. format \"single\" : moment court et percutant de {d['single_min']} a {d['single_max']} s.\n"
        f"   format \"multipart\" : histoire longue en {d['min_parts']} parties ou plus de "
        f"{d['part_min']} a {d['part_max']} s chacune (au moins {d['min_parts'] * d['part_min']} s "
        "au total) ; part_breaks = les instants de coupe (fin d'une ligne), chaque partie finissant "
        "sur un suspense et la suivante repartant sur une accroche.\n"
        "   Une duree hors de ces bornes est rejetee.\n"
        "3. Aucun moment ne chevauche un segment SponsorBlock marque EXCLU.\n"
        "4. Pas de long silence au debut ni a la fin.\n"
        "5. Deux moments ne se recouvrent pas : entre deux decoupes concurrentes, garde la meilleure.\n"
    )


def _signals_text(
    meta: dict[str, Any],
    audio: dict[str, Any],
    vision: dict[str, Any] | None,
    rubric: dict[str, Any],
    settings: dict[str, Any],
) -> str:
    excluded = set(rubric["exclusions"]["sponsorblock_categories"])
    chapters = "\n".join(
        f"- [{_span(c['start_time'], c['end_time'])}] {c.get('title') or ''}" for c in meta.get("chapters") or []
    ) or "(aucun)"
    heatmap = " ".join(
        f"{h['start_time']:.0f}-{h['end_time']:.0f}:{h['value']:.2f}" for h in meta.get("heatmap") or []
    ) or "(absente)"
    sponsor = "\n".join(
        f"- [{_span(s['start_time'], s['end_time'])}] {s.get('category')}"
        + (" EXCLU" if s.get("category") in excluded else "")
        for s in meta.get("sponsorblock_segments") or []
    ) or "(aucun)"
    peaks = sorted(audio.get("peaks") or [], key=lambda p: -p["relative_db"])[: int(settings["max_audio_peaks"])]
    peaks_text = " ".join(
        f"{p['timecode']:.1f}(+{p['relative_db']:.1f}dB)" for p in sorted(peaks, key=lambda p: p["timecode"])
    ) or "(aucun)"
    frames = (vision or {}).get("frames") or []
    vision_text = "\n".join(
        f"- {f['timecode']:.1f} : {f.get('description', '')}" + (" (marquant)" if f.get("striking") else "")
        for f in frames
        if f.get("description")
    ) or "(pas de description d'images)"
    return (
        "## Signaux mesures (des indices, pas des verites)\n"
        f"Chapitres :\n{chapters}\n\n"
        f"Most replayed (courbe YouTube, debut-fin:valeur de 0 a 1, plus haut = plus revu) :\n{heatmap}\n\n"
        f"Pics d'energie audio (rires, cris, reactions ; timecode et hauteur au-dessus du fond) :\n{peaks_text}\n\n"
        f"Segments SponsorBlock :\n{sponsor}\n\n"
        f"Descriptions d'images cles :\n{vision_text}\n"
    )


def _examples_text(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return "## Decisions passees de l'humain\n(aucune pour l'instant)\n"

    def fmt(e: dict[str, Any]) -> str:
        m = e.get("moment") or {}
        text = (e.get("texte_moment") or "").strip().replace("\n", " ")[:_EXAMPLE_TEXT_CHARS]
        comment = f" (commentaire : {e['commentaire']})" if e.get("commentaire") else ""
        where = f"[{m['start']}-{m['end']}] " if "start" in m and "end" in m else ""
        return f"- {where}\"{text}\"{comment}"

    good = [fmt(e) for e in examples if e.get("decision") != "rejected"]
    bad = [fmt(e) for e in examples if e.get("decision") == "rejected"]
    return (
        "## Decisions passees de l'humain (d'autres videos : calibre-toi dessus)\n"
        "Retenus, a imiter :\n" + ("\n".join(good) or "(aucun)") + "\n"
        "Refuses, a eviter :\n" + ("\n".join(bad) or "(aucun)") + "\n"
    )


def _video_text(meta: dict[str, Any]) -> str:
    description = (meta.get("description") or "").strip()[:1500]
    return (
        "## Video\n"
        f"Titre : {meta.get('title') or ''}\n"
        f"Chaine : {meta.get('channel') or ''}\n"
        f"Duree : {meta.get('duration') or '?'} s\n"
        f"Description : {description}\n"
    )


_ROLE = (
    "Tu es monteur video, specialiste des clips verticaux courts (TikTok, Shorts, Reels) tires "
    "de videos longues : lives, podcasts, reportages, souvent sur GTA 6. "
)


def _moments_prompt(context: str, rubric: dict[str, Any], lines: list[str], part: tuple[int, int] | None) -> str:
    if part is None:
        scope = "## Transcription complete (une ligne par phrase : [debut-fin] en secondes)\n"
    else:
        scope = (
            f"## Transcription, extrait {part[0]}/{part[1]} (une ligne par phrase : [debut-fin] en "
            "secondes). Les extraits se recouvrent ; ne propose que des moments entierement "
            "contenus dans celui-ci.\n"
        )
    return (
        _ROLE
        + "Repere dans la transcription TOUS les moments qui peuvent faire un clip autonome et "
        "viral, et note chacun selon la grille. Propose aussi ceux dont tu doutes (en general 5 a 30 "
        "pour une video de plusieurs heures) : le tri se fait apres, sur tes notes.\n\n"
        + _grid_text(rubric)
        + "\n"
        + context
        + "\n"
        + scope
        + "\n".join(lines)
        + "\n\nPour chaque moment : hook_text d'abord, puis start, end, format, part_breaks, "
        "justification et enfin les notes."
    )


def _comparison_prompt(context: str, rubric: dict[str, Any], candidates: list[dict[str, Any]], sents: list[Sentence]) -> str:
    blocks = []
    for n, c in enumerate(candidates):
        text = " ".join(s.text for s in sents[c["_first"] : c["_last"] + 1])
        blocks.append(f"### id {n} [{_span(c['_start'], c['_end'])}] {c['format']}\n{text}")
    return (
        _ROLE
        + "La transcription etait trop longue pour un seul passage : ces candidats ont ete notes "
        "extrait par extrait. Compare-les maintenant entre eux et re-note chacun selon la grille, "
        "sur une echelle commune, en le jugeant sur son seul texte ci-dessous. Renvoie une note pour "
        "chaque id, sans en omettre.\n\n"
        + _grid_text(rubric)
        + "\n"
        + context
        + "\n## Candidats\n\n"
        + "\n\n".join(blocks)
    )


# --------------------------------------------------------------------------
# Traitement des candidats
# --------------------------------------------------------------------------


def _nearest(indices: range, target: float, key) -> int:
    return min(indices, key=lambda k: (abs(key(k) - target), k))


def _normalize(
    raw: dict[str, Any], sents: list[Sentence], rubric: dict[str, Any], excluded: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(candidat recale, None) ou (None, rejet motive)."""

    def reject(reason: str, start: float, end: float) -> tuple[None, dict[str, Any]]:
        return None, {
            "start": round(start, 1), "end": round(end, 1), "reason": reason,
            "justification": raw["justification"], "scores": raw["scores"],
        }

    if raw["end"] <= raw["start"]:
        return reject("bornes invalides (end <= start)", raw["start"], raw["end"])

    first = _nearest(range(len(sents)), raw["start"], lambda k: sents[k].start)
    last = _nearest(range(first, len(sents)), raw["end"], lambda k: sents[k].end)
    start, end = sents[first].start, sents[last].end

    for seg in excluded:
        if start < seg["end_time"] and seg["start_time"] < end:
            return reject(
                f"chevauche un segment SponsorBlock {seg.get('category')} "
                f"[{_span(seg['start_time'], seg['end_time'])}]",
                start, end,
            )

    d = rubric["durations"]
    tol = d["tolerance"]
    duration = end - start
    if raw["format"] == "single":
        low, high = d["single_min"] - tol, d["single_max"] + tol
        bounds = f"{d['single_min']}-{d['single_max']} s"
    else:
        low, high = d["min_parts"] * d["part_min"] - tol, math.inf
        bounds = f">= {d['min_parts'] * d['part_min']} s"
    if not low <= duration <= high:
        return reject(f"duree {duration:.1f} s hors bornes {raw['format']} ({bounds})", start, end)

    parts: list[dict[str, float]] = []
    if raw["format"] == "multipart" and raw["part_breaks"] and last > first:
        cuts = sorted({_nearest(range(first, last), b, lambda k: sents[k].end) for b in raw["part_breaks"]})
        bounds_idx = [first - 1, *cuts, last]
        parts = [
            {"start": _floor1(sents[a + 1].start), "end": _ceil1(sents[b].end)}
            for a, b in zip(bounds_idx, bounds_idx[1:])
        ]

    return {
        "_first": first,
        "_last": last,
        "_start": start,
        "_end": end,
        "format": raw["format"],
        "parts": parts,
        "scores": raw["scores"],
        "justification": raw["justification"],
        "hook_text": sents[first].text,
    }, None


def _visual_bonus(start: float, end: float, vision: dict[str, Any] | None, rubric: dict[str, Any]) -> float:
    """Bonus des images marquantes : une image ``striking`` dans le moment suffit."""
    striking = any(
        f.get("striking") and start <= f["timecode"] <= end for f in (vision or {}).get("frames") or []
    )
    return float(rubric["bonus"]["visual"]) if striking else 0.0


def _bonus(
    start: float, end: float, meta: dict[str, Any], audio: dict[str, Any], vision: dict[str, Any] | None,
    rubric: dict[str, Any],
) -> dict[str, float]:
    b = rubric["bonus"]
    duration = end - start
    covered = sum(
        max(0.0, min(end, h["end_time"]) - max(start, h["start_time"])) * h["value"]
        for h in meta.get("heatmap") or []
    )
    replayed = b["replayed"] * (covered / duration if duration > 0 else 0.0)
    n_peaks = sum(1 for p in audio.get("peaks") or [] if start <= p["timecode"] <= end)
    audio_bonus = b["audio_peaks"] * min(1.0, n_peaks / b["audio_peaks_full"]) if b["audio_peaks_full"] > 0 else 0.0
    visual = _visual_bonus(start, end, vision, rubric)
    total = min(float(b["max_total"]), replayed + audio_bonus + visual)
    return {
        "replayed": round(replayed, 2),
        "audio_peaks": round(audio_bonus, 2),
        "visual": round(visual, 2),
        "total": round(total, 2),
    }


def final_score(scores: dict[str, float], rubric: dict[str, Any], bonus_total: float = 0.0) -> float:
    """Moyenne des notes ponderee par la grille, x10, plus le bonus ;
    borne a 100 et arrondie au dixieme."""
    criteria = rubric["criteria"]
    total_weight = sum(c["weight"] for c in criteria.values())
    base = sum(scores[name] * c["weight"] for name, c in criteria.items()) / total_weight * 10
    return round(min(100.0, base + bonus_total), 1)


def _overlaps(c: dict[str, Any], others: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((k for k in others if c["_start"] < k["_end"] and k["_start"] < c["_end"]), None)


def _select(
    candidates: list[dict[str, Any]], rubric: dict[str, Any], exploration: tuple[float, int] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """(retenus, rejets motives, bloc exploration ou None) : rejet sous
    ``min_score``, puis, entre candidats qui se chevauchent, seul le mieux
    note reste. Avec ``exploration`` (part, graine), les clips d'exploration
    suivent les retenus (voir ``_explore``)."""
    kept: list[dict[str, Any]] = []
    rejected: list[tuple[dict[str, Any], str]] = []
    for c in sorted(candidates, key=lambda c: (-c["final_score"], c["_start"])):
        if c["final_score"] < rubric["min_score"]:
            rejected.append((c, f"score {c['final_score']} < min_score {rubric['min_score']}"))
            continue
        rival = _overlaps(c, kept)
        if rival is not None:
            rejected.append((c, f"chevauche un moment mieux note [{_span(rival['_start'], rival['_end'])}]"))
            continue
        kept.append(c)
    info = None
    if exploration is not None:
        share, seed = exploration
        target, chosen = _explore([c for c, _ in rejected], kept, share, seed)
        info = {"share": share, "seed": seed, "target": target, "chosen": len(chosen)}
        kept += chosen
    return kept, [{**_public(c), "reason": reason} for c, reason in rejected if not c.get("exploration")], info


def _dispersion(c: dict[str, Any]) -> float:
    """Ecart entre le score le plus haut et le plus bas des juges, chacun a
    son dernier tour dans la trace du jury."""
    latest: dict[str, float] = {}
    for rnd in c["jury"]["trace"]["rounds"]:
        latest.update({name: j["score"] for name, j in rnd["judges"].items()})
    return round(max(latest.values()) - min(latest.values()), 1)


def _explore(
    pool: list[dict[str, Any]], kept: list[dict[str, Any]], share: float, seed: int
) -> tuple[int, list[dict[str, Any]]]:
    """(nombre vise, clips d'exploration marques) : parmi ``pool`` (candidats
    notes non retenus), les plus disperses d'abord, egalites departagees par
    un tirage a graine fixe, sans chevaucher un retenu ni un autre clip
    d'exploration. Moins de candidats possibles que vise : on prend ce qu'il
    y a, et ``chosen`` < ``target`` le dit."""
    target = max(0, math.floor(share * len(kept) + 0.5))
    rng = random.Random(f"{seed}:exploration")
    draw = {id(c): rng.random() for c in sorted(pool, key=lambda c: c["_start"])}
    chosen: list[dict[str, Any]] = []
    for c in sorted(pool, key=lambda c: (-_dispersion(c), draw[id(c)])):
        if len(chosen) >= target:
            break
        if _overlaps(c, kept + chosen) is None:
            c["exploration"] = True
            chosen.append(c)
    return target, chosen


def _rubric_info(rubric_path: Path, rubric: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(rubric_path),
        "weights": {name: c["weight"] for name, c in rubric["criteria"].items()},
        "min_score": rubric["min_score"],
    }


def _public(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "start": _floor1(c["_start"]),
        "end": _ceil1(c["_end"]),
        "duration": round(c["_end"] - c["_start"], 1),
        "format": c["format"],
        "parts": c["parts"],
        "scores": c["scores"],
        "bonus": c["bonus"],
        "final_score": c["final_score"],
        "justification": c["justification"],
        "hook_text": c["hook_text"],
        **({"jury": c["jury"]} if "jury" in c else {}),
        **({"exploration": True} if c.get("exploration") else {}),
    }


# --------------------------------------------------------------------------
# Jury
# --------------------------------------------------------------------------


def _judge(
    candidates: list[dict[str, Any]], sents: list[Sentence], rubric: dict[str, Any], context: str, config: Any
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Fait noter les candidats par clipper.jury ; renvoie (deroulement du
    jury sans les candidats, candidats non vetes, rejets pour veto). Les
    notes agregees du jury remplacent celles du proposeur, gardees avec la
    trace du jury dans ``jury`` de chaque candidat."""
    items = [
        {
            "id": f"m{n}",
            "text": " ".join(s.text for s in sents[c["_first"] : c["_last"] + 1]),
            "context": f"[{_span(c['_start'], c['_end'])}] s, {c['format']}",
        }
        for n, c in enumerate(candidates)
    ]
    result = jury.deliberate(items, rubric, context=context, config=config)
    kept: list[dict[str, Any]] = []
    vetoed: list[dict[str, Any]] = []
    for c, verdict in zip(candidates, result["candidates"], strict=True):
        c["jury"] = {
            "proposer": {"scores": c["scores"], "justification": c["justification"]},
            **{k: verdict[k] for k in ("score", "veto", "debated", "trace")},
        }
        c["scores"] = verdict["scores"]
        if verdict["veto"] is None:
            kept.append(c)
            continue
        # Sans final_score : la re-notation apres vision ne le reprend pas.
        vetoed.append({
            "start": _floor1(c["_start"]),
            "end": _ceil1(c["_end"]),
            "reason": f"veto du juge {verdict['veto']['judge']} : {verdict['veto']['reason']}",
            "format": c["format"],
            "hook_text": c["hook_text"],
            "justification": c["justification"],
            "scores": c["scores"],
            "jury": c["jury"],
        })
    return {k: v for k, v in result.items() if k != "candidates"}, kept, vetoed


# --------------------------------------------------------------------------
# Etape
# --------------------------------------------------------------------------


def _read_json(path: Path, optional: bool = False) -> Any:
    if not path.exists():
        if optional:
            return None
        raise MomentsError(f"entree absente : {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _settings(config: Any) -> dict[str, Any]:
    return {**CONFIG_DEFAULTS, **config.section("moments")}


def _selection(config: Any, settings: dict[str, Any]) -> str:
    """"jury" en mode auto (ADR-ff87) ou si [moments] selection = "jury" ;
    sinon "single"."""
    selection = settings["selection"]
    if selection not in SELECTIONS:
        raise MomentsError(f"[moments] selection invalide : {selection!r} (attendu : {' | '.join(SELECTIONS)})")
    return "jury" if config.mode == "auto" else selection


def _exploration(settings: dict[str, Any]) -> tuple[float, int] | None:
    """(part, graine) de l'exploration, None si la part vaut 0 ; un reglage
    invalide est une MomentsError."""
    share, seed = settings["exploration_share"], settings["exploration_seed"]
    if not _number(share) or not 0 <= share <= 1:
        raise MomentsError(f"[moments] exploration_share invalide : {share!r} (attendu : nombre de 0 a 1)")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise MomentsError(f"[moments] exploration_seed invalide : {seed!r} (attendu : entier)")
    return (float(share), seed) if share > 0 else None


def run(
    video_id: str,
    workspace_dir: str | Path = "workspace",
    *,
    config: Any = None,
    force: bool = False,
    examples: list[dict[str, Any]] | None = None,
) -> Path:
    """Choisit les moments de la video et ecrit workspace/<video_id>/moments.json,
    dont le chemin est renvoye. Un resultat deja present n'est pas refait,
    sauf ``force`` ; si vision.json est plus recent que lui, il est seulement
    re-note, sans appel LLM (voir ``_rescore``)."""
    if config is None:
        from clipper.config import load_config

        config = load_config()
    video_dir = Path(workspace_dir) / video_id
    out = video_dir / "moments.json"
    if out.exists() and not force:
        vision_path = video_dir / "vision.json"
        if vision_path.exists() and vision_path.stat().st_mtime_ns > out.stat().st_mtime_ns:
            return _rescore(video_dir, out, _settings(config))
        return out

    meta = _read_json(video_dir / "meta.json")
    transcript = _read_json(video_dir / "transcript.json")
    audio = _read_json(video_dir / "audio.json")
    vision = _read_json(video_dir / "vision.json", optional=True)
    settings = _settings(config)
    selection = _selection(config, settings)
    exploration = _exploration(settings) if selection == "jury" else None
    rubric_path = Path(settings["rubric_path"])
    rubric = load_rubric(rubric_path)
    examples = list(examples or [])

    sents = split_sentences(transcript)
    if not sents:
        raise MomentsError(f"transcription vide : {video_dir / 'transcript.json'}")
    excluded_categories = set(rubric["exclusions"]["sponsorblock_categories"])
    excluded = [s for s in meta.get("sponsorblock_segments") or [] if s.get("category") in excluded_categories]

    context = _signals_text(meta, audio, vision, rubric, settings) + "\n" + _examples_text(examples) + "\n" + _video_text(meta)
    schema = response_schema(rubric)
    lines = [_line(s) for s in sents]
    chunked = sum(len(line) + 1 for line in lines) > int(settings["max_transcript_chars"])
    if chunked:
        chunks = _chunks(sents, int(settings["chunk_chars"]), float(settings["chunk_overlap_seconds"]))
        raws = []
        for n, chunk in enumerate(chunks, 1):
            prompt = _moments_prompt(context, rubric, [_line(s) for s in chunk], (n, len(chunks)))
            raws += llm.ask("moments", prompt, [], schema, config=config)["moments"]
    else:
        raws = llm.ask("moments", _moments_prompt(context, rubric, lines, None), [], schema, config=config)["moments"]

    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for raw in raws:
        candidate, rejection = _normalize(raw, sents, rubric, excluded)
        if rejection is not None:
            rejected.append(rejection)
        elif (candidate["_first"], candidate["_last"]) not in seen:
            seen.add((candidate["_first"], candidate["_last"]))
            candidates.append(candidate)
    candidates.sort(key=lambda c: c["_start"])

    jury_info = None
    if selection == "jury":
        # Le jury note tous les candidats ensemble : pas de tour de comparaison.
        jury_info, candidates, vetoed = _judge(candidates, sents, rubric, context, config)
        rejected += vetoed
    elif chunked and candidates:
        answer = llm.ask(
            "moments",
            _comparison_prompt(context, rubric, candidates, sents),
            [],
            comparison_schema(rubric, len(candidates)),
            config=config,
        )
        ids = [m["id"] for m in answer["moments"]]
        missing = sorted(set(range(len(candidates))) - set(ids))
        if missing or len(ids) != len(set(ids)):
            raise llm.SchemaError(f"tour de comparaison : ids manquants {missing} ou en double dans {ids}")
        for m in answer["moments"]:
            candidates[m["id"]]["scores"] = m["scores"]
            candidates[m["id"]]["justification"] = m["justification"]

    for c in candidates:
        c["bonus"] = _bonus(c["_start"], c["_end"], meta, audio, vision, rubric)
        c["final_score"] = final_score(c["scores"], rubric, c["bonus"]["total"])

    kept, rejected_scored, exploration_info = _select(candidates, rubric, exploration)

    result = {
        "video_id": video_id,
        "rubric": _rubric_info(rubric_path, rubric),
        "chunked": chunked,
        "selection": selection,
        **({"jury": jury_info} if jury_info is not None else {}),
        **({"exploration": exploration_info} if exploration_info is not None else {}),
        "moments": [{"id": n, **_public(c)} for n, c in enumerate(kept)],
        "rejected": rejected + rejected_scored,
    }
    _write(out, result)
    return out


def _write(out: Path, result: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)


def _restore(entry: dict[str, Any], sents: list[Sentence], retained: bool) -> dict[str, Any]:
    """Candidat enregistre dans moments.json, avec ses bornes exactes
    retrouvees sur les phrases de la transcription (les bornes publiques sont
    arrondies au dixieme et creeraient de faux chevauchements)."""
    first = _nearest(range(len(sents)), entry["start"], lambda k: sents[k].start)
    last = _nearest(range(first, len(sents)), entry["end"], lambda k: sents[k].end)
    if (_floor1(sents[first].start), _ceil1(sents[last].end)) != (entry["start"], entry["end"]):
        raise MomentsError(
            f"moment [{entry['start']}-{entry['end']}] de moments.json hors des frontieres de phrase "
            "de transcript.json : re-notation impossible, relancer moments avec --force"
        )
    return {
        "_start": sents[first].start,
        "_end": sents[last].end,
        "_before": {"final_score": entry["final_score"], "retained": retained},
        **{k: entry[k] for k in ("format", "parts", "scores", "bonus", "final_score", "justification", "hook_text")},
        **({"jury": entry["jury"]} if "jury" in entry else {}),
    }


def _rescore(video_dir: Path, out: Path, settings: dict[str, Any]) -> Path:
    """Re-notation apres vision, sans LLM : sur les candidats deja notes de
    moments.json (retenus, rejetes pour score ou chevauchement), recalcule le
    bonus visuel, le score final, le filtre min_score et le non-chevauchement.
    Notes par critere, bornes et justifications restent celles enregistrees ;
    les rejets de la grille (SponsorBlock, duree, bornes) sont gardes tels
    quels. En selection par jury, l'exploration est refaite sur le meme
    principe. ``rescored.changed`` liste les candidats dont le score ou le
    sort (retenu ou non) a change."""
    previous = _read_json(out)
    vision = _read_json(video_dir / "vision.json")
    sents = split_sentences(_read_json(video_dir / "transcript.json"))
    rubric_path = Path(settings["rubric_path"])
    rubric = load_rubric(rubric_path)
    b = rubric["bonus"]

    candidates = [_restore(m, sents, True) for m in previous["moments"]]
    candidates += [_restore(r, sents, False) for r in previous["rejected"] if "final_score" in r]
    unscored = [r for r in previous["rejected"] if "final_score" not in r]
    for c in candidates:
        old = c["bonus"]
        visual = _visual_bonus(c["_start"], c["_end"], vision, rubric)
        if visual != old["visual"]:
            total = min(float(b["max_total"]), old["replayed"] + old["audio_peaks"] + visual)
            c["bonus"] = {**old, "visual": round(visual, 2), "total": round(total, 2)}
        c["final_score"] = final_score(c["scores"], rubric, c["bonus"]["total"])

    exploration = _exploration(settings) if previous.get("selection") == "jury" else None
    kept, rejected_scored, exploration_info = _select(candidates, rubric, exploration)
    moments_out = [{"id": n, **_public(c)} for n, c in enumerate(kept)]
    ids = {id(c): n for n, c in enumerate(kept)}
    changed = []
    for c in sorted(candidates, key=lambda c: c["_start"]):
        after = {"final_score": c["final_score"], "retained": id(c) in ids}
        if after != c["_before"]:
            changed.append({
                "id": ids.get(id(c)),
                "start": _floor1(c["_start"]),
                "end": _ceil1(c["_end"]),
                "hook_text": c["hook_text"],
                "before": c["_before"],
                "after": after,
            })

    result = {
        **{k: v for k, v in previous.items() if k != "exploration"},
        "rubric": _rubric_info(rubric_path, rubric),
        **({"exploration": exploration_info} if exploration_info is not None else {}),
        "moments": moments_out,
        "rejected": unscored + rejected_scored,
        "rescored": {"source": "vision.json", "changed": changed},
    }
    _write(out, result)
    return out
