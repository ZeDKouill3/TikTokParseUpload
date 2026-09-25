"""Jury de juges IA pour les decisions de jugement du mode auto (ADR-ff87).

Bibliotheque, pas une etape : les etapes l'appellent, elle n'importe aucune
etape (ADR-b16b) et passe par clipper.llm pour chaque appel (ADR-b1c1).

    from clipper import jury
    result = jury.deliberate(
        [{"id": "m3", "text": "...", "context": "[812.4-851.0] s, single"}],
        rubric,                        # {"criteria": {nom: {"weight", "question"}}, "trend_keywords"?}
        context="Titre, chaine, signaux de la video...",
    )

Deroulement :
1. Tour 1, a l'aveugle : chaque juge configure note tous les candidats en un
   seul appel (usage ``jury_<nom>``), juges en parallele. Les candidats sont
   anonymises (C1, C2... dans l'ordre ou le juge les voit) et melanges de
   facon deterministe, avec une graine propre a chaque juge (``seed``).
2. Desaccord : un candidat dont les scores par juge (0-100, grille ponderee)
   s'ecartent de plus de ``threshold`` passe au debat.
3. Tour 2 (un seul) sur ces candidats : chaque juge relit ses notes et son
   argument, puis les arguments anonymes des autres, et peut reviser.
4. Agregation : mediane par critere des notes finales de chaque juge, score
   = moyenne ponderee des medianes x10. Quand le fichier de poids de
   clipper.jury_calibration existe (``weights_path``, defaut
   state/jury_weights.json), la mediane par critere est ponderee par le poids
   de chaque juge (1 pour un juge absent du fichier) ; un juge a veto doit y
   valoir 1, et un fichier illisible est une JuryError (ADR-1cf0, ADR-ad2e).
   Le veto motive d'un juge ``veto`` (tour final) rejette le candidat : c'est
   a l'etape d'en tirer la consequence (ici on ne supprime rien).

Retour (serialisable en JSON, a ecrire dans le JSON de l'etape) :

    {"judges": [{"name", "usage", "model", "veto"}], "seed", "threshold",
     "quorum", "weights": None | {nom: poids},
     "failed": [{"judge", "round", "error"}], "debated": [id],
     "candidates": [{"id", "scores": {critere: mediane}, "score", "veto":
                     None | {"judge", "reason"}, "debated",
                     "trace": {"rounds": [{"round", "judges": {nom: {"scores",
                               "score", "argument", ("veto", "veto_reason")}}}],
                               "revisions": [{"judge", "criterion", "from",
                                              "to", "argument"}],
                               "dissent": [{"judge", "score", "median"}]}}]}

``candidates`` garde l'ordre d'entree. ``dissent`` : juges dont le score
final s'ecarte de la mediane des scores de plus de ``threshold``.

Echecs (ADR-ad2e) : une reponse de juge invalide (JSON, schema, candidat
manquant ou en double, veto sans raison) leve llm.SchemaError. Avec
``quorum`` configure, un juge invalide est ecarte (trace dans ``failed``)
tant qu'au moins ``quorum`` juges repondent correctement a ce tour ; sous le
quorum, JuryError. Un juge ``veto`` reste toujours obligatoire (sinon la
conformite sauterait en silence), et les erreurs transitoires (quota,
reseau) ou d'appel remontent toujours, quel que soit le quorum : la video
repart en file d'attente. Au tour 2, un juge ecarte garde ses notes du
tour 1, sans revision.

Configuration ([jury], fusionnee en profondeur avec CONFIG_DEFAULTS) :

    [jury]
    threshold = 20          # ecart de score (0-100) qui declenche le debat
    quorum = 4              # facultatif : juges valides minimum par tour
    seed = 0

    [jury.judges.retention]
    model = "sonnet"        # niveau (strong|fast) ou nom de modele

    [jury.judges.avocat]
    enabled = false

    [jury.judges.historien] # juge ajoute : perspective obligatoire
    perspective = "..."

``model`` d'un juge prime sur [llm.usages.jury_<nom>] ; sans ``model``,
c'est [llm] qui decide pour cet usage.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from clipper import llm

_RETENTION = (
    "Retention. Tu raisonnes comme l'algorithme de TikTok : un clip vit ou meurt sur le temps "
    "de visionnage. Demande-toi : la toute premiere phrase (les 3 premieres secondes) cree-t-elle "
    "une tension, une question ou une promesse qui oblige a rester ? Le rythme tient-il sans temps "
    "mort ni tunnel d'explication ? La fin donne-t-elle envie de revoir, de commenter ou de "
    "partager ? Un debut lent ou une chute molle font decrocher : sanctionne-les nettement, meme "
    "si le fond est interessant."
)

_SPECTATEUR = (
    "Spectateur cible. Tu as 16-30 ans, tu scrolles ton fil TikTok en France le soir, le pouce pret "
    "a passer. Tu suis le sujet de la video sans en etre expert et tu ne connais ni la chaine ni la "
    "personne qui parle. Lis chaque candidat comme s'il apparaissait dans ton fil : je m'arrete ou "
    "je scrolle, et a quel mot je decroche ? Est-ce que je like, je commente, je l'envoie a un "
    "pote ? Juge avec tes reactions de spectateur, pas avec un regard de professionnel : ce qui "
    "t'ennuie ou te perd ennuie et perd le public."
)

_MONTEUR = (
    "Monteur. Tu dois publier ce passage tel quel, coupe au debut et a la fin, sans voix off ni "
    "carton d'explication. Verifie : se comprend-il seul (aucun \"comme je disais\", aucun "
    "\"il\" ou \"ca\" dont on ignore a quoi il renvoie, aucune reference a ce qui precede) ? "
    "Commence-t-il directement sur l'accroche plutot que sur une mise en contexte ? Finit-il sur "
    "une phrase complete et une chute nette (punchline, revelation, conclusion), pas au milieu "
    "d'une idee ? Un contexte indispensable qui manque doit se voir dans standalone et payoff."
)

_AVOCAT = (
    "Avocat du diable. Ton role est de trouver ce qui fera echouer le clip, pas de l'aimer. Cherche "
    "le defaut le plus grave : contexte manquant, accroche qui promet plus que la suite ne donne, "
    "info deja vue partout, blague qui ne marche que si l'on connait le createur, passage mou au "
    "milieu, fin qui tombe a plat. Ne mets une note haute que si tu n'as rien trouve de serieux "
    "apres avoir vraiment cherche, et nomme toujours le principal defaut dans ton argument, meme "
    "pour un bon candidat."
)

_CONFORMITE = (
    "Conformite. Tu verifies que le clip peut etre publie sans risque sur TikTok en France. Risques : "
    "diffamation (accusation precise et non etayee contre une personne reelle identifiable), mineur "
    "identifiable, violence ou contenu choquant gratuit, haine ou harcelement, contenu sexuel, "
    "incitation a un acte dangereux, desinformation grave, clip qui repose sur une oeuvre protegee "
    "(musique, film, extrait d'une autre chaine). Pose un veto seulement pour un risque reel et "
    "precis, que tu cites dans veto_reason (le passage, le risque) ; un sujet sensible traite "
    "normalement, un gros mot ou une pique legere ne suffisent pas. Note aussi la grille avec ton "
    "regard : un clip qui frole la limite perd de sa valeur."
)

CONFIG_DEFAULTS: dict[str, object] = {
    # Composition du jury (ADR-ff87). Chaque juge : usage LLM, modele
    # (niveau strong|fast ou nom, prime sur [llm.usages.<usage>]), veto,
    # perspective (le prompt propre au juge). Modeles varies : diversite.
    "judges": {
        "retention": {"usage": "jury_retention", "model": "strong", "veto": False, "perspective": _RETENTION},
        "spectateur": {"usage": "jury_spectateur", "model": "fast", "veto": False, "perspective": _SPECTATEUR},
        "monteur": {"usage": "jury_monteur", "model": "strong", "veto": False, "perspective": _MONTEUR},
        "avocat": {"usage": "jury_avocat", "model": "strong", "veto": False, "perspective": _AVOCAT},
        "conformite": {"usage": "jury_conformite", "model": "fast", "veto": True, "perspective": _CONFORMITE},
    },
    # Ecart (points sur 100) entre le score le plus haut et le plus bas des
    # juges au-dela duquel un candidat passe au debat.
    "threshold": 20,
    # Nombre minimal de juges valides par tour ; absent : tous obligatoires.
    "quorum": None,
    # Graine du melange des candidats (propre a chaque juge).
    "seed": 0,
    # Appels LLM simultanes (un par juge et par tour).
    "parallel": 5,
}

_JUDGE_KEYS = {"enabled", "usage", "model", "veto", "perspective"}
_MIN_JUDGES = 3
_ARGUMENT_CHARS = 500


class JuryError(Exception):
    """Configuration du jury ou candidats invalides, ou quorum non atteint."""


# --------------------------------------------------------------------------
# Reglages
# --------------------------------------------------------------------------


def _deep_merge(base: Mapping[str, Any], top: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in top.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _judges(settings: dict[str, Any]) -> list[dict[str, Any]]:
    judges = []
    for name, entry in settings["judges"].items():
        unknown = set(entry) - _JUDGE_KEYS
        if unknown:
            raise JuryError(f"[jury.judges.{name}] : cle(s) inconnue(s) {sorted(unknown)}")
        if not entry.get("enabled", True):
            continue
        perspective = entry.get("perspective")
        if not isinstance(perspective, str) or not perspective.strip():
            raise JuryError(f"[jury.judges.{name}] : perspective manquante")
        judges.append(
            {
                "name": name,
                "usage": entry.get("usage", f"jury_{name}"),
                "model": entry.get("model"),
                "veto": bool(entry.get("veto", False)),
                "perspective": perspective,
            }
        )
    if len(judges) < _MIN_JUDGES:
        raise JuryError(f"il faut au moins {_MIN_JUDGES} juges actifs, {len(judges)} configure(s)")
    quorum = settings["quorum"]
    if quorum is not None and not (isinstance(quorum, int) and 1 <= quorum <= len(judges)):
        raise JuryError(f"[jury] quorum invalide : {quorum!r} (entier de 1 a {len(judges)})")
    return judges


class _JudgeConfig:
    """Vue de la config pour un juge : son ``model`` remplace celui de
    [llm.usages.<usage>], le reste est la config d'origine."""

    def __init__(self, config: Any, usage: str, model: str | None):
        self._config, self._usage, self._model = config, usage, model

    def section(self, name: str) -> dict[str, Any]:
        table = self._config.section(name)
        if name != "llm" or not self._model:
            return table
        usages = dict(table.get("usages", {}))
        usages[self._usage] = {**usages.get(self._usage, {}), "model": self._model}
        return {**table, "usages": usages}

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._config, attr)


def _check_candidates(candidates: Sequence[Mapping[str, Any]]) -> None:
    seen = set()
    for n, c in enumerate(candidates):
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            raise JuryError(f"candidat {n} : id manquant")
        if cid in seen:
            raise JuryError(f"candidat {n} : id {cid!r} en double")
        seen.add(cid)
        if not isinstance(c.get("text"), str) or not c["text"].strip():
            raise JuryError(f"candidat {cid!r} : texte manquant")


# --------------------------------------------------------------------------
# Prompts et schemas
# --------------------------------------------------------------------------


def _schema(criteria: Mapping[str, Any], refs: list[str], veto: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "ref": {"type": "string", "enum": refs},
        "argument": {
            "type": "string", "minLength": 1, "maxLength": _ARGUMENT_CHARS,
            "description": "Une ou deux phrases concretes, qui citent le passage decisif.",
        },
        "scores": {
            "type": "object",
            "description": "Note entiere de 0 a 10 par critere de la grille.",
            "properties": {
                name: {"type": "integer", "minimum": 0, "maximum": 10, "description": c["question"]}
                for name, c in criteria.items()
            },
            "required": list(criteria),
            "additionalProperties": False,
        },
    }
    if veto:
        item["veto"] = {"type": "boolean", "description": "true seulement pour un risque reel et precis."}
        item["veto_reason"] = {
            "type": "string", "maxLength": _ARGUMENT_CHARS,
            "description": "Si veto : le passage et le risque ; sinon chaine vide.",
        }
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": len(refs),
                "maxItems": len(refs),
                "items": {
                    "type": "object",
                    "properties": item,
                    "required": list(item),
                    "additionalProperties": False,
                },
            },
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


def _grid_text(rubric: Mapping[str, Any]) -> str:
    criteria = "\n".join(f"- {name} : {c['question']}" for name, c in rubric["criteria"].items())
    keywords = rubric.get("trend_keywords")
    trend = f"Mots-cles tendance : {', '.join(keywords)}\n" if keywords else ""
    return (
        "## Grille : une note entiere de 0 a 10 par critere\n"
        f"{criteria}\n{trend}"
        "Echelle : 0-2 absent, 3-4 faible, 5-6 correct, 7-8 fort, 9-10 exceptionnel (rare). "
        "Une note gonflee fait publier un mauvais clip, une note ecrasee en fait perdre un bon : "
        "sers-toi de toute l'echelle.\n"
    )


def _frame(judge: dict[str, Any], n_judges: int, rubric: Mapping[str, Any], context: str) -> str:
    veto = (
        "Tu es le seul juge a pouvoir poser un veto : veto = true rejette le candidat quelles que "
        "soient les notes, veto_reason dit pourquoi.\n\n"
        if judge["veto"]
        else ""
    )
    return (
        f"Tu fais partie d'un jury de {n_judges} juges qui decide quels extraits d'une video longue "
        "deviennent des clips TikTok pour un public francophone. Chaque juge a sa perspective ; les "
        "notes sont agregees par mediane. Reste strictement dans ta perspective : c'est elle qui rend "
        "le jury utile.\n\n"
        f"## Ta perspective\n{judge['perspective']}\n\n"
        + veto
        + _grid_text(rubric)
        + (f"\n## Contexte de la video\n{context}\n" if context else "")
    )


def _block(ref: str, candidate: Mapping[str, Any]) -> str:
    ctx = candidate.get("context")
    return f"### {ref}\n" + (f"Contexte : {ctx}\n" if ctx else "") + f"Texte : « {candidate['text']} »"


def _round1_prompt(frame: str, shown: list[tuple[str, Mapping[str, Any]]]) -> str:
    return (
        frame
        + f"\n## Candidats ({len(shown)}), dans un ordre aleatoire\n\n"
        + "\n\n".join(_block(ref, c) for ref, c in shown)
        + "\n\n## Consignes\n"
        "Note chaque candidat sur son seul texte, independamment des autres et de sa place dans la "
        "liste. Pour chacun : ref, puis argument (une ou deux phrases concretes qui citent entre "
        "guillemets le passage decisif et disent ce qui marche ou bloque de ton point de vue, sans "
        "formule generique), puis les notes. Un element par candidat, sans en omettre."
    )


def _round2_prompt(
    frame: str,
    shown: list[tuple[str, Mapping[str, Any]]],
    own: dict[str, dict[str, Any]],
    others: dict[str, list[str]],
    veto: bool,
) -> str:
    blocks = []
    for ref, c in shown:
        mine = own[ref]
        notes = ", ".join(f"{k} {v}" for k, v in mine["scores"].items())
        heard = "\n".join(f"- Avis {n} : {arg}" for n, arg in enumerate(others[ref], 1))
        vetoed = f"Ton veto au tour 1 : {mine['veto_reason']}\n" if veto and mine["veto"] else ""
        blocks.append(
            _block(ref, c)
            + f"\nTes notes au tour 1 : {notes}\nTon argument : {mine['argument']}\n"
            + vetoed
            + f"Autres avis :\n{heard}"
        )
    return (
        frame
        + "\n## Debat\nLe jury diverge sur les candidats ci-dessous. Pour chacun, tu retrouves tes "
        "notes et ton argument du premier tour, puis les arguments des autres juges, anonymes et "
        "dans un ordre aleatoire. Lis-les honnetement en restant dans ta perspective. Revise une note "
        "seulement si un argument t'apporte un fait precis que tu avais manque ou mal lu dans le "
        "texte ; ne t'aligne jamais pour faire consensus ni parce qu'un avis revient souvent.\n\n"
        + "\n\n".join(blocks)
        + "\n\n## Consignes\nPour chaque candidat : ref, puis argument (ce qui a change et pourquoi, "
        "ou pourquoi tu maintiens, en une ou deux phrases), puis toutes tes notes, revisees ou non."
        + (" Redonne aussi veto et veto_reason, maintenus ou leves." if veto else "")
    )


# --------------------------------------------------------------------------
# Appels
# --------------------------------------------------------------------------


def _ask(
    judge: dict[str, Any],
    prompt: str,
    refs: list[str],
    criteria: Mapping[str, Any],
    config: Any,
) -> dict[str, dict[str, Any]]:
    """ref -> {"scores", "argument", ("veto", "veto_reason")} ; toute reponse
    incomplete ou incoherente est une llm.SchemaError."""
    answer = llm.ask(
        judge["usage"],
        prompt,
        [],
        _schema(criteria, refs, judge["veto"]),
        config=_JudgeConfig(config, judge["usage"], judge["model"]),
    )
    out: dict[str, dict[str, Any]] = {}
    for item in answer["candidates"]:
        ref = item["ref"]
        if ref in out:
            raise llm.SchemaError(f"juge {judge['name']} : {ref} note deux fois")
        entry = {"scores": dict(item["scores"]), "argument": item["argument"]}
        if judge["veto"]:
            if item["veto"] and not item["veto_reason"].strip():
                raise llm.SchemaError(f"juge {judge['name']} : veto sans raison sur {ref}")
            entry["veto"] = item["veto"]
            entry["veto_reason"] = item["veto_reason"] if item["veto"] else ""
        out[ref] = entry
    return out


def _run_round(
    rnd: int,
    tasks: dict[str, Any],
    judges: list[dict[str, Any]],
    quorum: int | None,
    parallel: int,
    failed: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Lance ``tasks`` (nom de juge -> appel sans argument) en parallele ;
    renvoie nom -> reponse pour les juges valides, selon la regle du quorum."""
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(tasks)))) as executor:
        futures = {name: executor.submit(task) for name, task in tasks.items()}
    answers, errors = {}, {}
    for judge in judges:
        name = judge["name"]
        if name not in futures:
            continue
        try:
            answers[name] = futures[name].result()
        except llm.SchemaError as exc:
            if quorum is None or judge["veto"]:
                raise
            errors[name] = exc
    for name, exc in errors.items():
        failed.append({"judge": name, "round": rnd, "error": str(exc)})
    if errors and len(answers) < quorum:
        raise JuryError(
            f"tour {rnd} : quorum non atteint ({len(answers)} juge(s) valide(s) sur {len(tasks)}, "
            f"quorum {quorum}) : "
            + " ; ".join(f"{name} : {exc}" for name, exc in errors.items())
        )
    return answers


# --------------------------------------------------------------------------
# Agregation
# --------------------------------------------------------------------------


def _weights(config: Any, judges: list[dict[str, Any]]) -> dict[str, float] | None:
    """Poids par juge actif du fichier ecrit par clipper.jury_calibration
    (lu via sa section de config, sans l'importer), None s'il n'existe pas."""
    path = Path(config.section("jury_calibration")["weights_path"])
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        loaded = {name: float(entry["weight"]) for name, entry in data["judges"].items()}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise JuryError(f"poids du jury : {path} illisible : {exc}") from exc
    weights = {j["name"]: loaded.get(j["name"], 1.0) for j in judges}
    for j in judges:
        w = weights[j["name"]]
        if not (math.isfinite(w) and w > 0):
            raise JuryError(f"poids du jury : {path} : poids invalide pour {j['name']} : {w!r}")
        if (j["veto"] or j["name"] == "conformite") and w != 1.0:
            raise JuryError(
                f"poids du jury : {j['name']} vaut {w} dans {path}, "
                "le juge conformite (ou a veto) garde le poids 1 (ADR-1cf0)"
            )
    return weights


def _weighted_median(values: Sequence[tuple[float, float]]) -> float:
    """Mediane de (valeur, poids) : premiere valeur ou le poids cumule
    atteint la moitie du total, moyenne avec la suivante si la moitie tombe
    pile sur la frontiere (egale a statistics.median a poids egaux)."""
    ordered = sorted(values)
    half = sum(w for _, w in ordered) / 2
    cumul = 0.0
    for n, (value, weight) in enumerate(ordered):
        cumul += weight
        if math.isclose(cumul, half):
            return (value + ordered[n + 1][0]) / 2
        if cumul > half:
            return value
    return ordered[-1][0]


def _score(scores: Mapping[str, float], criteria: Mapping[str, Any]) -> float:
    total = sum(c["weight"] for c in criteria.values())
    return round(sum(scores[name] * c["weight"] for name, c in criteria.items()) / total * 10, 1)


def _spread(notes: Mapping[str, dict[str, Any]], criteria: Mapping[str, Any]) -> float:
    values = [_score(n["scores"], criteria) for n in notes.values()]
    return max(values) - min(values)


def _round_record(rnd: int, notes: Mapping[str, dict[str, Any]], criteria: Mapping[str, Any]) -> dict[str, Any]:
    judges = {}
    for name, n in notes.items():
        entry = {"scores": n["scores"], "score": _score(n["scores"], criteria), "argument": n["argument"]}
        if "veto" in n:
            entry["veto"] = n["veto"]
            entry["veto_reason"] = n["veto_reason"]
        judges[name] = entry
    return {"round": rnd, "judges": judges}


def deliberate(
    candidates: Sequence[Mapping[str, Any]],
    rubric: Mapping[str, Any],
    *,
    context: str = "",
    config: Any = None,
) -> dict[str, Any]:
    """Fait juger ``candidates`` (id, text, context facultatif) par le jury
    configure, sur la grille ``rubric`` ; voir la docstring du module."""
    if config is None:
        from clipper.config import load_config

        config = load_config()
    settings = _deep_merge(CONFIG_DEFAULTS, config.section("jury"))
    judges = _judges(settings)
    weights = _weights(config, judges)
    _check_candidates(candidates)
    criteria = rubric["criteria"]
    threshold = float(settings["threshold"])
    quorum = settings["quorum"]
    seed = settings["seed"]
    parallel = int(settings["parallel"])
    failed: list[dict[str, Any]] = []
    by_id = {c["id"]: c for c in candidates}

    # Tour 1 : ordre et refs propres a chaque juge.
    views: dict[str, dict[str, str]] = {}  # juge -> ref -> id
    tasks = {}
    for judge in judges:
        ids = [c["id"] for c in candidates]
        random.Random(f"{seed}:{judge['name']}").shuffle(ids)
        refs = {f"C{n}": cid for n, cid in enumerate(ids, 1)}
        views[judge["name"]] = refs
        shown = [(ref, by_id[cid]) for ref, cid in refs.items()]
        prompt = _round1_prompt(_frame(judge, len(judges), rubric, context), shown)
        tasks[judge["name"]] = (lambda j=judge, p=prompt, r=list(refs): _ask(j, p, r, criteria, config))
    answers = _run_round(1, tasks, judges, quorum, parallel, failed) if candidates else {}
    active = [j for j in judges if j["name"] in answers]

    # roundN[id][juge] = {"scores", "argument", ("veto", "veto_reason")}
    round1 = {cid: {j["name"]: answers[j["name"]][_ref(views[j["name"]], cid)] for j in active} for cid in by_id}
    debated = [cid for cid in by_id if _spread(round1[cid], criteria) > threshold]

    # Tour 2 : debat sur les seuls desaccords.
    round2: dict[str, dict[str, dict[str, Any]]] = {cid: {} for cid in debated}
    if debated:
        tasks = {}
        for judge in active:
            name = judge["name"]
            ids = list(debated)
            rng = random.Random(f"{seed}:{name}:2")
            rng.shuffle(ids)
            shown, own, others = [], {}, {}
            for cid in ids:
                ref = _ref(views[name], cid)
                shown.append((ref, by_id[cid]))
                own[ref] = round1[cid][name]
                heard = [round1[cid][o["name"]]["argument"] for o in active if o["name"] != name]
                rng.shuffle(heard)
                others[ref] = heard
            prompt = _round2_prompt(_frame(judge, len(judges), rubric, context), shown, own, others, judge["veto"])
            tasks[name] = (lambda j=judge, p=prompt, r=[s[0] for s in shown]: _ask(j, p, r, criteria, config))
        answers2 = _run_round(2, tasks, active, quorum, parallel, failed)
        for name, answer in answers2.items():
            for ref, entry in answer.items():
                round2[views[name][ref]][name] = entry

    results = []
    for cid in by_id:
        final = {**round1[cid], **round2.get(cid, {})}
        if weights is None:
            scores = {name: statistics.median(n["scores"][name] for n in final.values()) for name in criteria}
        else:
            scores = {
                name: _weighted_median([(n["scores"][name], weights[j]) for j, n in final.items()])
                for name in criteria
            }
        judge_scores = {name: _score(n["scores"], criteria) for name, n in final.items()}
        median = statistics.median(judge_scores.values())
        veto = next(
            ({"judge": j["name"], "reason": final[j["name"]]["veto_reason"]}
             for j in active if j["veto"] and final[j["name"]]["veto"]),
            None,
        )
        rounds = [_round_record(1, round1[cid], criteria)]
        revisions = []
        if cid in round2:
            rounds.append(_round_record(2, round2[cid], criteria))
            for name, entry in round2[cid].items():
                for crit in criteria:
                    before, after = round1[cid][name]["scores"][crit], entry["scores"][crit]
                    if before != after:
                        revisions.append(
                            {"judge": name, "criterion": crit, "from": before, "to": after, "argument": entry["argument"]}
                        )
        dissent = [
            {"judge": name, "score": s, "median": median}
            for name, s in judge_scores.items()
            if abs(s - median) > threshold
        ]
        results.append(
            {
                "id": cid,
                "scores": scores,
                "score": _score(scores, criteria),
                "veto": veto,
                "debated": cid in round2,
                "trace": {"rounds": rounds, "revisions": revisions, "dissent": dissent},
            }
        )

    return {
        "judges": [{k: j[k] for k in ("name", "usage", "model", "veto")} for j in judges],
        "seed": seed,
        "threshold": threshold,
        "quorum": quorum,
        "weights": weights,
        "failed": failed,
        "debated": debated,
        "candidates": results,
    }


def _ref(view: Mapping[str, str], cid: str) -> str:
    return next(ref for ref, c in view.items() if c == cid)
