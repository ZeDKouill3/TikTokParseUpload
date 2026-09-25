"""Calibration des poids des juges a partir des resultats reels (ADR-1cf0 point 2).

Bibliotheque, pas une etape : n'importe aucune etape (ADR-b16b). Mesure, pour
chaque juge, a quel point ses notes (trace du jury, voir clipper.jury)
prevoyaient les resultats reels du journal des resultats (clipper.outcomes),
et en deduit un poids d'agregation borne. Jamais l'accord entre juges : seuls
les signaux reels comptent.

    from clipper import jury_calibration
    jury_calibration.calibrate([
        {"video_id": "abc123", "moment_id": 3,
         "candidate": <entree de jury.deliberate()["candidates"]>},
        ...
    ])

L'appelant relie chaque candidat juge au moment qu'il est devenu
(``video_id``, ``moment_id``, ceux du journal des resultats). La note d'un
juge est son score (0-100) au dernier tour ou il a note ce candidat.

Resultat reel d'un moment (0-1) : moyenne des signaux du journal, dans la
fenetre ``window_days`` (sur ``recorded_at``) :
- qa : ``passed`` 1, ``rejected`` 0 ;
- decision humaine : ``accepted``/``approved``/``adjusted`` 1, ``rejected``
  0 ; toute autre valeur est une CalibrationError ;
- statistiques de plateforme : ``stats_metric`` (fraction 0-1, defaut
  ``watched_full``).

Les statistiques importees du CSV n'ont que ``clip_id`` (video_id et
moment_id valent None). Elles sont reliees a un moment par les entrees
``result`` du journal (tout le journal, pas seulement la fenetre) qui portent
le meme ``clip_id`` avec leur ``video_id``/``moment_id``. Hypothese
d'unicite : un ``clip_id`` du CSV designe un seul clip de tout le journal.
Les clip_id produits par clipper.captions (``03``, ``03-p1``) ne sont uniques
que dans une video : un clip_id porte par plusieurs (video_id, moment_id) est
ambigu. Une statistique ambigue ou sans entree reliee n'est jamais attribuee
au hasard : elle est ecartee, journalisee (logging) et listee dans
``ignored_stats`` du fichier de poids.

Poids d'un juge :
- accord = correlation de rang (Spearman) entre ses notes et les resultats
  reels, sur les moments qui ont les deux ;
- moins de ``min_clips`` moments (ou accord indefini : notes ou resultats
  tous egaux) : poids 1, raison dans ``reason`` ;
- sinon cible = 1 + accord x (max_weight - 1) si accord >= 0, 1 + accord x
  (1 - min_weight) sinon ; lissage avec le poids precedent (fichier
  existant, 1 sinon) : poids = smoothing x precedent + (1 - smoothing) x
  cible, borne a [min_weight, max_weight] ;
- le juge conformite, et tout juge a veto (cle ``veto`` dans sa trace),
  garde toujours le poids 1 (ADR-1cf0 point 5).

Fichier ecrit (``weights_path``, defaut state/jury_weights.json), relu par
clipper.jury (mediane ponderee) :

    {"computed_at", "window": {"since", "until", "days"}, "min_clips",
     "bounds": [min, max], "smoothing", "stats_metric",
     "judges": {nom: {"weight", "agreement", "clips", "previous", "target",
                      "fixed", "reason"}},
     "ignored_stats": [{"clip_id", "reason": "ambiguous" | "unlinked",
                        "matches": [[video_id, moment_id], ...]}]}
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from clipper import outcomes

log = logging.getLogger(__name__)

CONFIG_DEFAULTS: dict[str, object] = {
    # Fichier des poids dates, relu par clipper.jury quand il existe.
    "weights_path": "state/jury_weights.json",
    # Fenetre des resultats pris en compte (jours avant la calibration).
    "window_days": 90,
    # Moments relies minimum pour qu'un juge quitte le poids 1.
    "min_clips": 20,
    # Bornes du poids (ADR-1cf0).
    "min_weight": 0.5,
    "max_weight": 1.5,
    # Part du poids precedent conservee (0 : pas de lissage).
    "smoothing": 0.5,
    # Statistique de plateforme retenue comme resultat (fraction 0-1).
    "stats_metric": "watched_full",
}

# Jamais recalibres sur l'audience (ADR-1cf0 point 5), en plus des juges a veto.
FIXED_JUDGES = ("conformite",)

_POSITIVE_DECISIONS = ("accepted", "approved", "adjusted")
_NEGATIVE_DECISIONS = ("rejected",)
_QA = {"passed": 1.0, "rejected": 0.0}


class CalibrationError(Exception):
    """Reglage invalide ou resultat du journal illisible."""


# --------------------------------------------------------------------------
# Fichier de poids
# --------------------------------------------------------------------------


def _previous(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {name: float(entry["weight"]) for name, entry in data["judges"].items()}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CalibrationError(f"{path} illisible : {exc}") from exc


# --------------------------------------------------------------------------
# Resultats reels
# --------------------------------------------------------------------------


def _signals(entry: Mapping[str, Any], metric: str) -> list[float]:
    if entry.get("kind") == "stats":
        stats = entry.get("stats") or {}
        if metric not in stats:
            raise CalibrationError(f"statistique {metric!r} absente pour le clip {entry.get('clip_id')!r}")
        return [float(stats[metric])]
    values = []
    qa = entry.get("qa")
    if qa is not None:
        status = qa.get("status")
        if status not in _QA:
            raise CalibrationError(f"statut qa inconnu {status!r} (clip {entry.get('clip_id')!r})")
        values.append(_QA[status])
    decision = entry.get("human_decision")
    if decision is not None:
        if decision in _POSITIVE_DECISIONS:
            values.append(1.0)
        elif decision in _NEGATIVE_DECISIONS:
            values.append(0.0)
        else:
            raise CalibrationError(f"decision humaine inconnue {decision!r} (clip {entry.get('clip_id')!r})")
    return values


def _at(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _outcomes(
    journal: list[dict[str, Any]], since: datetime, metric: str
) -> tuple[dict[tuple[Any, Any], float], list[dict[str, Any]]]:
    """(video_id, moment_id) -> resultat reel 0-1, et statistiques ecartees."""
    owners: dict[str, set[tuple[Any, Any]]] = defaultdict(set)
    for e in journal:
        if e.get("kind") == "result":
            owners[e["clip_id"]].add((e["video_id"], e["moment_id"]))

    values: dict[tuple[Any, Any], list[float]] = defaultdict(list)
    ignored: list[dict[str, Any]] = []
    for e in journal:
        if _at(e["recorded_at"]) < since:
            continue
        if e.get("kind") == "stats":
            matches = sorted(owners.get(e["clip_id"], set()), key=repr)
            if len(matches) != 1:
                reason = "ambiguous" if matches else "unlinked"
                log.warning("statistique du clip %r ecartee de la calibration : %s %s", e["clip_id"], reason, matches)
                ignored.append({"clip_id": e["clip_id"], "reason": reason, "matches": [list(m) for m in matches]})
                continue
            key = matches[0]
        else:
            key = (e["video_id"], e["moment_id"])
        values[key].extend(_signals(e, metric))
    return {k: sum(v) / len(v) for k, v in values.items() if v}, ignored


# --------------------------------------------------------------------------
# Accord
# --------------------------------------------------------------------------


def _final_scores(candidate: Mapping[str, Any]) -> tuple[dict[str, float], set[str]]:
    """Score de chaque juge a son dernier tour, et juges a veto."""
    scores: dict[str, float] = {}
    veto: set[str] = set()
    for rnd in sorted(candidate["trace"]["rounds"], key=lambda r: r["round"]):
        for name, entry in rnd["judges"].items():
            scores[name] = float(entry["score"])
            if "veto" in entry:
                veto.add(name)
    return scores, veto


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------


def _settings(config: Any) -> dict[str, Any]:
    s = dict(config.section("jury_calibration"))
    lo, hi = float(s["min_weight"]), float(s["max_weight"])
    if not (0 < lo <= 1 <= hi):
        raise CalibrationError(f"[jury_calibration] bornes invalides : min_weight {lo} <= 1 <= max_weight {hi} attendu")
    smoothing = float(s["smoothing"])
    if not 0 <= smoothing < 1:
        raise CalibrationError(f"[jury_calibration] smoothing invalide : {smoothing} (0 <= smoothing < 1)")
    if not (isinstance(s["min_clips"], int) and s["min_clips"] >= 2):
        raise CalibrationError(f"[jury_calibration] min_clips invalide : {s['min_clips']!r} (entier >= 2)")
    return {**s, "min_weight": lo, "max_weight": hi, "smoothing": smoothing, "window_days": float(s["window_days"])}


def calibrate(
    traces: Iterable[Mapping[str, Any]],
    *,
    config: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calcule les poids des juges (voir la docstring du module), les ecrit
    dates dans ``weights_path`` et les renvoie."""
    if config is None:
        from clipper.config import load_config

        config = load_config()
    s = _settings(config)
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=s["window_days"])
    path = Path(config.section("jury_calibration")["weights_path"])
    previous = _previous(path)

    journal = outcomes.read(config.section("outcomes")["journal_path"])
    results, ignored = _outcomes(journal, since, s["stats_metric"])

    pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    fixed = set(FIXED_JUDGES)
    judges: list[str] = []
    for t in traces:
        scores, veto = _final_scores(t["candidate"])
        fixed |= veto
        judges += [name for name in scores if name not in judges]
        outcome = results.get((t["video_id"], t["moment_id"]))
        if outcome is None:
            continue
        for name, score in scores.items():
            pairs[name].append((score, outcome))

    out: dict[str, dict[str, Any]] = {}
    for name in judges:
        data = pairs.get(name, [])
        entry: dict[str, Any] = {
            "weight": 1.0, "agreement": None, "clips": len(data), "previous": previous.get(name),
            "target": None, "fixed": name in fixed, "reason": None,
        }
        if data:
            entry["agreement"] = _spearman([a for a, _ in data], [b for _, b in data])
        if name in fixed:
            entry["reason"] = "fixed"
        elif len(data) < s["min_clips"]:
            entry["reason"] = "min_clips"
        elif entry["agreement"] is None:
            entry["reason"] = "undefined_agreement"
        else:
            agreement = entry["agreement"]
            span = s["max_weight"] - 1 if agreement >= 0 else 1 - s["min_weight"]
            target = 1 + agreement * span
            prev = previous.get(name, 1.0)
            weight = s["smoothing"] * prev + (1 - s["smoothing"]) * target
            entry["target"] = round(target, 4)
            entry["weight"] = round(min(s["max_weight"], max(s["min_weight"], weight)), 4)
        out[name] = entry

    record = {
        "computed_at": now.isoformat(),
        "window": {"since": since.isoformat(), "until": now.isoformat(), "days": s["window_days"]},
        "min_clips": s["min_clips"],
        "bounds": [s["min_weight"], s["max_weight"]],
        "smoothing": s["smoothing"],
        "stats_metric": s["stats_metric"],
        "judges": out,
        "ignored_stats": ignored,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record
