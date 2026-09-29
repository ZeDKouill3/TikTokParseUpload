"""Coach des prompts du jury : propose des retouches par juge, rejouees sur
des candidats passes au resultat connu (ADR-1cf0 point 3).

Bibliotheque, pas une etape (ADR-b16b) ; commande manuelle : n'est appelee
depuis nulle part dans clipper.pipeline, jamais au fil de l'eau. Une
retouche adoptee n'est ecrite que dans un fichier prompts/jury/<juge>/vN.md,
jamais dans clipper.jury ni dans le fichier de poids du jury : l'adoption
reelle du prompt (le faire lire par clipper.jury) reste un acte separe.

    from clipper import jury_coach
    proposals = jury_coach.propose(cases, rubric, judges, config=config)

``cases`` : candidats passes dont le resultat est connu, chacun avec son
texte/contexte d'origine et la trace du jury qui l'a juge (voir
clipper.jury.deliberate) :

    {"video_id", "moment_id", "text", "context",
     "trace": <candidat["trace"] de jury.deliberate()>}

``judges`` : nom de juge -> perspective actuelle (le texte du prompt en
place), pour tout juge actif du jury -- sert a rejouer l'ancienne version et
a detecter un rapprochement entre deux perspectives.

Deroulement, par juge (``conformite`` est toujours exclu, ADR-1cf0 point 5,
jamais coache meme s'il figure dans ``judges`` ou ``cases``) :

1. Relie chaque cas a son resultat reel (0-1) via le journal des resultats
   (clipper.outcomes, entrees ``kind: result`` seulement : qa et decision
   humaine, moyennees si les deux sont presentes ; les statistiques de
   plateforme n'existent pas encore dans ce journal, ADR-1cf0 point 1).
   Moins de ``min_cases`` cas relies pour ce juge : pas de proposition
   (raison ``pas assez de cas connus``), rien n'est demande a clipper.llm.
2. Deja ``max_lessons_per_judge`` versions adoptees pour ce juge (fichiers
   prompts/jury/<juge>/vN.md existants) : refus immediat (raison ``plafond
   de lecons atteint``), rien n'est demande a clipper.llm non plus.
3. Retient les ``lessons_per_call`` cas ou la note passee du juge (dernier
   tour de sa trace) s'ecarte le plus du resultat reel, et demande a
   clipper.llm (usage ``[jury_coach] usage``, defaut ``coach``) une
   retouche de perspective avec sa justification.
4. Refuse (raison ``perspective trop proche de <juge>``) si la nouvelle
   perspective se rapproche trop (ratio ``difflib.SequenceMatcher``
   au-dela de ``similarity_threshold``) de la perspective d'un autre juge
   actif : le jury n'a pas interet a uniformiser ses perspectives
   (ADR-1cf0). Aucun rejeu n'est tente dans ce cas.
5. Sinon rejoue l'ANCIENNE puis la NOUVELLE perspective sur les memes cas
   (un appel clipper.llm par cas et par version, usage ``jury_<juge>``,
   comme en jugement reel). Metrique documentee : erreur absolue moyenne
   entre la note predite (0-1) et le resultat reel sur ces cas, plus bas
   est mieux. La proposition n'est adoptable que si cette erreur baisse
   strictement (raison ``ne predit pas mieux en rejeu`` sinon).
6. Si adoptable : ecrit prompts/jury/<juge>/vN.md (N = version suivante non
   utilisee pour ce juge) avec la perspective proposee, sa justification et
   la metrique avant/apres.

Retour : une entree par juge non exclu present dans ``judges`` :

    {"judge", "accepted", "reason": str | None, "version": int | None,
     "path": str | None, "metric": {"before", "after", "cases"} | None}
"""

from __future__ import annotations

import difflib
import re
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from clipper import llm, outcomes

CONFIG_DEFAULTS: dict[str, object] = {
    # Dossier des propositions versionnees, une sous-arborescence par juge.
    "prompts_dir": "prompts/jury",
    # Usage LLM (clipper.llm) pour demander une retouche de perspective.
    "usage": "coach",
    # Cas relies a un resultat connu, minimum pour proposer une retouche.
    "min_cases": 5,
    # Cas les plus mal predits envoyes au coach comme lecons.
    "lessons_per_call": 5,
    # Versions adoptees au-dela desquelles ce juge n'est plus retouche.
    "max_lessons_per_judge": 5,
    # Similarite (0-1, difflib) entre deux perspectives au-dela de laquelle
    # une retouche est refusee (ADR-1cf0 : jamais uniformiser le jury).
    "similarity_threshold": 0.6,
    # Fenetre des resultats pris en compte (jours avant l'appel).
    "window_days": 90,
}

# Jamais coache, meme recalibre sur l'audience : son veto reste independant
# des resultats (ADR-1cf0 point 5).
EXCLUDED_JUDGES = ("conformite",)

_QA = {"passed": 1.0, "rejected": 0.0}
_POSITIVE_DECISIONS = ("accepted", "approved", "adjusted")
_NEGATIVE_DECISIONS = ("rejected",)
_VERSION_RE = re.compile(r"^v(\d+)\.md$")


class CoachError(Exception):
    """Reglage invalide, ou entree du journal des resultats illisible."""


# --------------------------------------------------------------------------
# Journal des resultats
# --------------------------------------------------------------------------


def _at(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _real_outcomes(journal: list[dict[str, Any]], since: datetime) -> dict[tuple[Any, Any], float]:
    """(video_id, moment_id) -> resultat reel (0-1), moyenne de qa et de la
    decision humaine sur les entrees ``result`` du journal depuis ``since``."""
    values: dict[tuple[Any, Any], list[float]] = defaultdict(list)
    for e in journal:
        if e.get("kind") != "result" or _at(e["recorded_at"]) < since:
            continue
        signals: list[float] = []
        qa = e.get("qa")
        if qa is not None:
            status = qa.get("status")
            if status not in _QA:
                raise CoachError(f"statut qa inconnu {status!r} (clip {e.get('clip_id')!r})")
            signals.append(_QA[status])
        decision = e.get("human_decision")
        if decision is not None:
            if decision in _POSITIVE_DECISIONS:
                signals.append(1.0)
            elif decision in _NEGATIVE_DECISIONS:
                signals.append(0.0)
            else:
                raise CoachError(f"decision humaine inconnue {decision!r} (clip {e.get('clip_id')!r})")
        if signals:
            values[(e["video_id"], e["moment_id"])].extend(signals)
    return {k: sum(v) / len(v) for k, v in values.items()}


# --------------------------------------------------------------------------
# Cas d'un juge
# --------------------------------------------------------------------------


def _last_score(trace: Mapping[str, Any], judge: str) -> dict[str, Any] | None:
    entry = None
    for rnd in sorted(trace["rounds"], key=lambda r: r["round"]):
        if judge in rnd["judges"]:
            entry = rnd["judges"][judge]
    return entry


def _judge_cases(
    cases: Sequence[Mapping[str, Any]], judge: str, real_outcomes: Mapping[tuple[Any, Any], float]
) -> list[dict[str, Any]]:
    matched = []
    for case in cases:
        outcome = real_outcomes.get((case["video_id"], case["moment_id"]))
        if outcome is None:
            continue
        entry = _last_score(case["trace"], judge)
        if entry is None:
            continue
        matched.append(
            {
                "text": case["text"],
                "context": case.get("context", ""),
                "argument": entry["argument"],
                "predicted": float(entry["score"]) / 100,
                "outcome": outcome,
            }
        )
    return matched


# --------------------------------------------------------------------------
# Demande de retouche
# --------------------------------------------------------------------------


def _lesson_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "perspective": {"type": "string", "minLength": 1},
            "justification": {"type": "string", "minLength": 1},
        },
        "required": ["perspective", "justification"],
        "additionalProperties": False,
    }


def _grid_text(criteria: Mapping[str, Any]) -> str:
    return "\n".join(f"- {name} : {c['question']}" for name, c in criteria.items())


def _lesson_prompt(judge: str, perspective: str, criteria: Mapping[str, Any], worst: list[dict[str, Any]]) -> str:
    cases_text = "\n\n".join(
        f"### Cas {n}\nTexte : « {c['text']} »\nContexte : {c['context']}\n"
        f"Sa note passee : {round(c['predicted'] * 100)}/100 (argument : {c['argument']})\n"
        f"Resultat reel : {round(c['outcome'] * 100)}/100"
        for n, c in enumerate(worst, 1)
    )
    return (
        f"Tu coaches le juge {judge} d'un jury qui note des extraits de video pour en faire des clips "
        "TikTok. Voici sa perspective actuelle :\n\n"
        f"{perspective}\n\n"
        f"## Grille\n{_grid_text(criteria)}\n\n"
        "## Cas ou ce juge s'est le plus trompe (note passee vs resultat reel, sur 100)\n\n"
        f"{cases_text}\n\n"
        "## Consigne\nPropose une nouvelle version complete de sa perspective, prete a l'emploi, qui "
        "garde son role et son point de vue propres mais l'aiderait a mieux predire ces resultats. "
        "Justifie le changement a partir des cas ci-dessus."
    )


# --------------------------------------------------------------------------
# Rejeu
# --------------------------------------------------------------------------


def _replay_schema(criteria: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "scores": {
                "type": "object",
                "properties": {name: {"type": "integer", "minimum": 0, "maximum": 10} for name in criteria},
                "required": list(criteria),
                "additionalProperties": False,
            },
        },
        "required": ["scores"],
        "additionalProperties": False,
    }


def _replay_prompt(perspective: str, criteria: Mapping[str, Any], case: Mapping[str, Any]) -> str:
    return (
        f"{perspective}\n\n"
        f"## Grille : une note entiere de 0 a 10 par critere\n{_grid_text(criteria)}\n\n"
        f"## Candidat\nContexte : {case['context']}\nTexte : « {case['text']} »\n\n"
        "Note ce candidat sur son seul texte, un entier de 0 a 10 par critere."
    )


def _predicted_score(scores: Mapping[str, int], criteria: Mapping[str, Any]) -> float:
    total = sum(c["weight"] for c in criteria.values())
    return sum(scores[name] * c["weight"] for name, c in criteria.items()) / total / 10


def _replay(judge: str, perspective: str, criteria: Mapping[str, Any], cases: list[dict[str, Any]], config: Any) -> float:
    """Rejoue ``perspective`` sur ``cases`` (usage jury_<judge>, comme en
    jugement reel) ; renvoie l'erreur absolue moyenne entre la note predite
    (0-1) et le resultat reel (metrique documentee du module)."""
    schema = _replay_schema(criteria)
    errors = []
    for case in cases:
        answer = llm.ask(f"jury_{judge}", _replay_prompt(perspective, criteria, case), [], schema, config=config)
        predicted = _predicted_score(answer["scores"], criteria)
        errors.append(abs(predicted - case["outcome"]))
    return statistics.mean(errors)


# --------------------------------------------------------------------------
# Similarite et versions
# --------------------------------------------------------------------------


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _too_similar(judge: str, new_perspective: str, judges: Mapping[str, str], threshold: float) -> str | None:
    for other, perspective in judges.items():
        if other != judge and _similarity(new_perspective, perspective) > threshold:
            return other
    return None


def _existing_versions(judge_dir: Path) -> list[int]:
    if not judge_dir.exists():
        return []
    versions = []
    for path in judge_dir.iterdir():
        match = _VERSION_RE.match(path.name)
        if match:
            versions.append(int(match.group(1)))
    return sorted(versions)


def _write_version(judge_dir: Path, version: int, perspective: str, justification: str, metric: dict[str, Any]) -> Path:
    judge_dir.mkdir(parents=True, exist_ok=True)
    path = judge_dir / f"v{version}.md"
    content = (
        f"# {judge_dir.name} v{version}\n\n"
        f"{perspective.strip()}\n\n"
        "## Justification\n"
        f"{justification.strip()}\n\n"
        "## Metrique (erreur absolue moyenne entre note predite et resultat reel, plus bas est mieux)\n"
        f"- avant : {metric['before']:.4f}\n"
        f"- apres : {metric['after']:.4f}\n"
        f"- cas rejoues : {metric['cases']}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Commande
# --------------------------------------------------------------------------


def propose(
    cases: Sequence[Mapping[str, Any]],
    rubric: Mapping[str, Any],
    judges: Mapping[str, str],
    *,
    config: Any = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Propose une retouche de perspective par juge non exclu de ``judges``,
    validee par rejeu (voir la docstring du module)."""
    if config is None:
        from clipper.config import load_config

        config = load_config()
    settings = config.section("jury_coach")
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=float(settings["window_days"]))
    journal = outcomes.read(config.section("outcomes")["journal_path"])
    real_outcomes = _real_outcomes(journal, since)
    prompts_dir = Path(settings["prompts_dir"])
    min_cases = int(settings["min_cases"])
    lessons_per_call = int(settings["lessons_per_call"])
    max_lessons = int(settings["max_lessons_per_judge"])
    threshold = float(settings["similarity_threshold"])
    usage = settings["usage"]
    criteria = rubric["criteria"]

    results: list[dict[str, Any]] = []
    for judge, perspective in judges.items():
        if judge in EXCLUDED_JUDGES:
            continue

        def _refuse(reason: str, metric: dict[str, Any] | None = None) -> None:
            results.append(
                {"judge": judge, "accepted": False, "reason": reason, "version": None, "path": None, "metric": metric}
            )

        judge_cases = _judge_cases(cases, judge, real_outcomes)
        if len(judge_cases) < min_cases:
            _refuse("pas assez de cas connus")
            continue

        judge_dir = prompts_dir / judge
        versions = _existing_versions(judge_dir)
        if len(versions) >= max_lessons:
            _refuse("plafond de lecons atteint")
            continue

        worst = sorted(judge_cases, key=lambda c: abs(c["predicted"] - c["outcome"]), reverse=True)[:lessons_per_call]
        answer = llm.ask(usage, _lesson_prompt(judge, perspective, criteria, worst), [], _lesson_schema(), config=config)
        new_perspective, justification = answer["perspective"], answer["justification"]

        clash = _too_similar(judge, new_perspective, judges, threshold)
        if clash is not None:
            _refuse(f"perspective trop proche de {clash}")
            continue

        before = _replay(judge, perspective, criteria, worst, config)
        after = _replay(judge, new_perspective, criteria, worst, config)
        metric = {"before": before, "after": after, "cases": len(worst)}
        if not after < before:
            _refuse("ne predit pas mieux en rejeu", metric)
            continue

        version = (max(versions) if versions else 0) + 1
        path = _write_version(judge_dir, version, new_perspective, justification, metric)
        results.append(
            {"judge": judge, "accepted": True, "reason": None, "version": version, "path": str(path), "metric": metric}
        )

    return results
