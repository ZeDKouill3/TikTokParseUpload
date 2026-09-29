from __future__ import annotations

import ast
import json
import os
import re
import threading
import time
from collections import defaultdict
from pathlib import Path

import pytest

from clipper import jury, llm
from clipper.config import Config
from clipper.llm.fake import FakeBackend

JUDGES = ["retention", "spectateur", "monteur", "avocat", "conformite"]

# Grille reduite : score = (3 x hook + 1 x standalone) / 4 x 10.
RUBRIC = {
    "criteria": {
        "hook": {"weight": 3, "question": "La 1re phrase arrete-t-elle le scroll ?"},
        "standalone": {"weight": 1, "question": "Comprehensible seul ?"},
    },
}


def candidates(n=3):
    return [
        {"id": f"secret-id-{k}", "text": f"texte numero {k} du passage", "context": f"[{k * 60}-{k * 60 + 30}] s"}
        for k in range(n)
    ]


def make_config(jury_table=None, llm_table=None):
    sections = {}
    if jury_table is not None:
        sections["jury"] = jury_table
    if llm_table is not None:
        sections["llm"] = llm_table
    return Config(mode="auto", workspace_dir=Path("workspace"), output_dir=Path("output"), _sections=sections)


def blocks(prompt):
    """ref -> texte du candidat, dans l'ordre de presentation du prompt."""
    out = {}
    for chunk in prompt.split("\n### ")[1:]:
        ref = chunk.split("\n", 1)[0].strip()
        match = re.search(r"« (.+?) »", chunk)
        if ref and match:
            out[ref] = match.group(1)
    return out


def cid_of(text):
    return "secret-id-" + re.search(r"texte numero (\d+)", text).group(1)


class ScriptedJury:
    """Repond pour chaque juge (usage jury_<nom>) selon un script :
    notes[round][juge][id] = note (tous criteres) ou dict critere -> note.
    Un tour absent du script reprend les notes du tour 1."""

    def __init__(self, notes, veto=None, raw=None, barrier=None):
        self.notes = notes
        self.veto = veto or {}  # (round, id) -> raison, pour le juge conformite
        self.raw = raw or {}  # (round, juge) -> reponse brute (str/dict)
        self.barrier = barrier
        self.lock = threading.Lock()
        self.count = defaultdict(int)
        self.prompts = defaultdict(list)  # juge -> [prompt tour 1, prompt tour 2]
        self.repairs = defaultdict(list)  # juge -> [tour de chaque reparation demandee]

    def __call__(self, request):
        judge = request.usage.removeprefix("jury_")
        with self.lock:
            # Une reparation (llm.ask renvoie la demande d'origine suivie de
            # l'erreur) reste dans le tour de la demande qu'elle repare.
            repaired = [n for n, p in enumerate(self.prompts[judge], 1) if request.prompt.startswith(p + "\n")]
            if repaired:
                rnd = repaired[-1]
                self.repairs[judge].append(rnd)
            else:
                self.count[judge] += 1
                rnd = self.count[judge]
                self.prompts[judge].append(request.prompt)
        if self.barrier is not None and rnd == 1 and not repaired:
            self.barrier.wait()
        if (rnd, judge) in self.raw:
            return self.raw[(rnd, judge)]
        table = self.notes.get(rnd, self.notes[1])[judge]
        answer = []
        for ref, text in blocks(request.prompt).items():
            cid = cid_of(text)
            note = table[cid]
            scores = note if isinstance(note, dict) else {c: note for c in RUBRIC["criteria"]}
            item = {"ref": ref, "argument": f"ARG-{judge}-r{rnd}-{cid}", "scores": scores}
            # Le schema (partage par tout le modele, TASK-b0fa) dit si veto
            # et veto_reason sont attendus dans la reponse, pas le nom du
            # juge : seul conformite (le juge a veto) fixe une raison via
            # self.veto, les autres juges du meme modele repondent veto=False.
            schema_item = request.schema["properties"]["candidates"]["items"]["properties"]
            if "veto" in schema_item:
                reason = self.veto.get((rnd, cid), "") if judge == "conformite" else ""
                item["veto"] = bool(reason)
                item["veto_reason"] = reason
            answer.append(item)
        return {"candidates": answer}


def uniform(value_by_id):
    return {j: dict(value_by_id) for j in JUDGES}


def run(script, cands=None, config=None, calls=12):
    fake = FakeBackend([script] * calls)
    with llm.use_backend(fake):
        result = jury.deliberate(cands if cands is not None else candidates(), RUBRIC, context="VIDEO-CTX", config=config or make_config())
    return result, fake


def by_id(result):
    return {c["id"]: c for c in result["candidates"]}


# --------------------------------------------------------------------------
# Bibliotheque, pas une etape
# --------------------------------------------------------------------------


def test_jury_imports_no_step_and_not_web():
    source = Path(jury.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            if node.module == "clipper":
                imported |= {f"clipper.{a.name}" for a in node.names}
    clipper_imports = {m for m in imported if m.startswith("clipper")}
    assert clipper_imports <= {"clipper", "clipper.llm", "clipper.config"}, clipper_imports


# --------------------------------------------------------------------------
# Composition par defaut
# --------------------------------------------------------------------------


def test_default_composition_five_judges_with_compliance_veto_and_model_per_judge():
    judges = jury.CONFIG_DEFAULTS["judges"]
    assert list(judges) == JUDGES
    assert [name for name, j in judges.items() if j.get("veto")] == ["conformite"]
    for name, j in judges.items():
        assert j["usage"] == f"jury_{name}"
        assert j["model"], name
        assert len(j["perspective"]) > 200, name
    assert len({j["perspective"] for j in judges.values()}) == 5


def test_config_table_is_accepted_by_load_config(tmp_path):
    from clipper.config import load_config

    path = tmp_path / "config.toml"
    path.write_text('[jury]\nthreshold = 15\nquorum = 4\n\n[jury.judges.retention]\nmodel = "sonnet"\n', encoding="utf-8")
    config = load_config(path)
    assert config.section("jury")["threshold"] == 15


# --------------------------------------------------------------------------
# Tour 1 : un appel par juge, via clipper.llm, en parallele, a l'aveugle
# --------------------------------------------------------------------------


def test_one_call_per_judge_with_its_usage_and_perspective():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    result, fake = run(script)
    assert sorted(c.usage for c in fake.calls) == sorted(f"jury_{j}" for j in JUDGES)
    for call in fake.calls:
        name = call.usage.removeprefix("jury_")
        assert jury.CONFIG_DEFAULTS["judges"][name]["perspective"] in call.prompt
        # tous les candidats dans un seul appel
        assert len(blocks(call.prompt)) == 3
        assert "VIDEO-CTX" in call.prompt
        assert "La 1re phrase arrete-t-elle le scroll ?" in call.prompt
    assert [c["id"] for c in result["candidates"]] == ["secret-id-0", "secret-id-1", "secret-id-2"]


def test_model_is_set_per_judge():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    config = make_config(
        jury_table={"judges": {"retention": {"model": "modele-retention"}, "monteur": {"model": "fast"}}},
        llm_table={"claude_cli": {"models": {"strong": "gros", "fast": "rapide"}}},
    )
    _, fake = run(script, config=config)
    models = {c.usage: c.model for c in fake.calls}
    assert models["jury_retention"] == "modele-retention"
    assert models["jury_monteur"] == "rapide"


def test_judges_run_in_two_waves_a_leader_per_model_then_the_rest():
    # 2 modeles par defaut (strong, fast) : 2 leaders d'abord (en parallele
    # entre eux), puis les 3 autres juges (en parallele entre eux), pour que
    # la 2e vague profite du cache de prompt chauffe par la 1re (meme
    # prefixe, meme modele). Les leaders sont ralentis : un suiveur ne doit
    # demarrer qu'une fois les DEUX leaders termines (mesure par horodatage,
    # pas par une barriere que le vieux comportement a une chance de croiser
    # par coincidence).
    leaders = {"retention", "spectateur"}
    followers = {"monteur", "avocat", "conformite"}
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    starts: dict[str, float] = {}
    finishes: dict[str, float] = {}
    lock = threading.Lock()

    def synced(request):
        judge = request.usage.removeprefix("jury_")
        with lock:
            starts[judge] = time.monotonic()
        if judge in leaders:
            time.sleep(0.2)
        answer = script(request)
        with lock:
            finishes[judge] = time.monotonic()
        return answer

    fake = FakeBackend([synced] * 5)
    with llm.use_backend(fake):
        jury.deliberate(candidates(), RUBRIC, config=make_config())

    assert len(fake.calls) == 5
    last_leader_finish = max(finishes[j] for j in leaders)
    for j in followers:
        assert starts[j] >= last_leader_finish, j
    order = [c.usage.removeprefix("jury_") for c in fake.calls]
    assert set(order[:2]) == leaders
    assert set(order[2:]) == followers


def test_candidates_are_anonymized():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    _, fake = run(script)
    for call in fake.calls:
        assert "secret-id" not in call.prompt
        assert set(blocks(call.prompt)) == {"C1", "C2", "C3"}
        assert "[60-90] s" in call.prompt  # le contexte du candidat est transmis


def test_same_model_judges_share_an_identical_prompt_prefix_for_the_cache():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    _, fake = run(script)
    prompts = {c.usage.removeprefix("jury_"): c.prompt for c in fake.calls}

    def prefix(name):
        return prompts[name].split("## Ta perspective")[0]

    assert prefix("retention") == prefix("monteur") == prefix("avocat")
    assert prefix("spectateur") == prefix("conformite")
    assert prefix("retention") != prefix("spectateur")


def test_prompt_prefix_before_the_role_includes_the_schema():
    # TASK-b0fa : le schema (--json-schema) doit faire partie de ce qui
    # precede la consigne de role, pas etre ajoute apres (llm.ask l'ajoute
    # de toute facon a la toute fin, en plus, mais ca ne casse pas ce
    # prefixe puisque c'est apres le role).
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    _, fake = run(script)
    prompts = {c.usage.removeprefix("jury_"): c.prompt for c in fake.calls}

    def prefix(name):
        return prompts[name].split("## Ta perspective")[0]

    for name in ("retention", "monteur", "avocat", "spectateur", "conformite"):
        schema_json = json.dumps(fake.calls[[c.usage.removeprefix("jury_") for c in fake.calls].index(name)].schema, ensure_ascii=False)
        assert schema_json in prefix(name), name
    # Le schema (candidats a noter, veto compris) est desormais partage par
    # tout le jury d'un meme modele : spectateur et conformite (tous deux
    # "fast" par defaut) partagent le meme schema, veto/veto_reason compris,
    # meme si seul conformite en tient compte (voir _ask).
    assert fake.calls[0].schema is not None


def test_round_one_is_blind():
    notes = {
        1: {j: {"secret-id-0": 2 if j == "avocat" else 9, "secret-id-1": 5, "secret-id-2": 3} for j in JUDGES},
    }
    script = ScriptedJury(notes)
    run(script)
    for judge, prompts in script.prompts.items():
        assert "ARG-" not in prompts[0], judge
        assert "Avis 1" not in prompts[0], judge
    # le prompt de tour 1 d'un juge ne depend en rien des notes des autres
    other = {1: {j: {"secret-id-0": 0 if j == "avocat" else 10, "secret-id-1": 1, "secret-id-2": 9} for j in JUDGES}}
    again = ScriptedJury(other)
    run(again)
    for judge in JUDGES:
        assert again.prompts[judge][0] == script.prompts[judge][0], judge


def order(prompt):
    return [cid_of(t) for t in blocks(prompt).values()]


def orders_for(seed):
    cands = candidates(8)
    script = ScriptedJury({1: uniform({c["id"]: 5 for c in cands})})
    run(script, cands=cands, config=make_config(jury_table={"seed": seed}))
    return {j: order(script.prompts[j][0]) for j in JUDGES}


def test_same_model_judges_share_the_llm_cache_prefix_field():
    # TASK-2cbb : le prefixe textuel commun (deja teste ci-dessus) ne suffit
    # pas a faire relire le cache par le modele : encore faut-il que
    # clipper.llm sache ou il se termine pour le marquer (LLMRequest.cache_prefix),
    # sans quoi claude_cli.stdin_input() ne peut jamais poser de cache_control
    # (voir claude_cli.py). Round 1 : chaque juge d'un meme modele doit porter
    # exactement le meme cache_prefix, egal a son prompt prive de son role.
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    _, fake = run(script)
    by_judge = {c.usage.removeprefix("jury_"): c for c in fake.calls}

    for name, call in by_judge.items():
        assert call.cache_prefix, name
        assert call.prompt.startswith(call.cache_prefix), name
        role_start = call.prompt.index("## Ta perspective")
        assert call.cache_prefix == call.prompt[:role_start], name

    assert by_judge["retention"].cache_prefix == by_judge["monteur"].cache_prefix == by_judge["avocat"].cache_prefix
    assert by_judge["spectateur"].cache_prefix == by_judge["conformite"].cache_prefix
    assert by_judge["retention"].cache_prefix != by_judge["spectateur"].cache_prefix


def test_round_two_debate_prompt_also_carries_a_cache_prefix():
    script = ScriptedJury({1: split_notes()})
    _, fake = run(script)
    second_calls = {
        c.usage.removeprefix("jury_"): c
        for c in fake.calls[len(JUDGES):]  # tour 2 : un appel de plus par juge
    }
    for name, call in second_calls.items():
        assert call.cache_prefix, name
        assert call.prompt.startswith(call.cache_prefix), name
        assert call.cache_prefix != call.prompt, name  # le role divergent suit bien le prefixe


def test_shuffle_is_deterministic_and_specific_to_each_model():
    first, again = orders_for(0), orders_for(0)
    assert first == again
    # meme modele (defaut : strong = retention/monteur/avocat, fast =
    # spectateur/conformite) => meme ordre, pour un prefixe de prompt commun.
    assert first["retention"] == first["monteur"] == first["avocat"]
    assert first["spectateur"] == first["conformite"]
    assert first["retention"] != first["spectateur"]
    assert any(o != [f"secret-id-{k}" for k in range(8)] for o in first.values())
    assert orders_for(1) != first


# --------------------------------------------------------------------------
# Debat cible
# --------------------------------------------------------------------------


def split_notes():
    # secret-id-0 : consensus (tous 7) ; secret-id-1 : avocat a 2, les autres a 8.
    return {j: {"secret-id-0": 7, "secret-id-1": 2 if j == "avocat" else 8, "secret-id-2": 5} for j in JUDGES}


def test_no_debate_without_disagreement():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 6, "secret-id-2": 5})})
    result, fake = run(script)
    assert len(fake.calls) == 5
    assert result["debated"] == []
    assert all(not c["debated"] for c in result["candidates"])
    assert all(len(c["trace"]["rounds"]) == 1 for c in result["candidates"])


def test_debate_only_on_disagreeing_candidates():
    script = ScriptedJury({1: split_notes()})
    result, fake = run(script)
    assert len(fake.calls) == 10
    assert result["debated"] == ["secret-id-1"]
    for judge in JUDGES:
        second = script.prompts[judge][1]
        assert [cid_of(t) for t in blocks(second).values()] == ["secret-id-1"]
        # les arguments scriptes (ARG-...) portent l'id ; le jury, jamais
        assert "secret-id" not in re.sub(r"ARG-\S+", "", second)


def test_debate_shows_other_arguments_anonymized():
    script = ScriptedJury({1: split_notes()})
    run(script)
    second = script.prompts["retention"][1]
    for other in ("spectateur", "monteur", "avocat", "conformite"):
        assert f"ARG-{other}-r1-secret-id-1" in second
    # ses propres notes et argument du tour 1
    assert "ARG-retention-r1-secret-id-1" in second
    # aucune perspective nommee : les avis des autres sont anonymes
    for other in ("spectateur", "monteur", "avocat", "conformite"):
        assert jury.CONFIG_DEFAULTS["judges"][other]["perspective"] not in second


def test_debate_threshold_is_configurable():
    script = ScriptedJury({1: split_notes()})
    result, fake = run(script, config=make_config(jury_table={"threshold": 60}))
    assert result["debated"] == []
    assert len(fake.calls) == 5


def test_revision_in_debate_is_used_and_traced():
    round2 = split_notes()
    round2["avocat"]["secret-id-1"] = 6
    script = ScriptedJury({1: split_notes(), 2: round2})
    result, _ = run(script)
    c = by_id(result)["secret-id-1"]
    assert c["debated"]
    assert c["trace"]["revisions"] == [
        {"judge": "avocat", "criterion": "hook", "from": 2, "to": 6, "argument": "ARG-avocat-r2-secret-id-1"},
        {"judge": "avocat", "criterion": "standalone", "from": 2, "to": 6, "argument": "ARG-avocat-r2-secret-id-1"},
    ]
    rounds = c["trace"]["rounds"]
    assert [r["round"] for r in rounds] == [1, 2]
    assert rounds[1]["judges"]["avocat"]["scores"] == {"hook": 6, "standalone": 6}


# --------------------------------------------------------------------------
# Agregation
# --------------------------------------------------------------------------


def test_median_per_criterion_and_weighted_score():
    notes = {
        "retention": {"hook": 9, "standalone": 2},
        "spectateur": {"hook": 8, "standalone": 4},
        "monteur": {"hook": 3, "standalone": 6},
        "avocat": {"hook": 7, "standalone": 5},
        "conformite": {"hook": 6, "standalone": 10},
    }
    table = {j: {"secret-id-0": notes[j]} for j in JUDGES}
    script = ScriptedJury({1: table})
    result, _ = run(script, cands=candidates(1), config=make_config(jury_table={"threshold": 100}))
    c = result["candidates"][0]
    assert c["scores"] == {"hook": 7, "standalone": 5}
    # (3 x 7 + 1 x 5) / 4 x 10
    assert c["score"] == 65.0
    assert c["veto"] is None


def test_median_uses_final_notes_after_debate():
    round2 = split_notes()
    for j in ("retention", "spectateur", "monteur"):
        round2[j]["secret-id-1"] = 3
    script = ScriptedJury({1: split_notes(), 2: round2})
    result, _ = run(script)
    assert by_id(result)["secret-id-1"]["scores"] == {"hook": 3, "standalone": 3}


def test_dissent_is_traced():
    script = ScriptedJury({1: split_notes()})
    result, _ = run(script)
    c = by_id(result)["secret-id-1"]
    assert c["trace"]["dissent"] == [{"judge": "avocat", "score": 20.0, "median": 80.0}]
    assert by_id(result)["secret-id-0"]["trace"]["dissent"] == []


def test_trace_holds_notes_and_arguments_per_judge_and_round():
    script = ScriptedJury({1: split_notes()})
    result, _ = run(script)
    c = by_id(result)["secret-id-0"]
    first = c["trace"]["rounds"][0]
    assert first["round"] == 1
    assert set(first["judges"]) == set(JUDGES)
    assert first["judges"]["monteur"] == {
        "scores": {"hook": 7, "standalone": 7},
        "score": 70.0,
        "argument": "ARG-monteur-r1-secret-id-0",
    }
    assert first["judges"]["conformite"]["veto"] is False
    assert [j["name"] for j in result["judges"]] == JUDGES


# --------------------------------------------------------------------------
# Veto
# --------------------------------------------------------------------------


def test_compliance_veto_rejects_with_reason():
    script = ScriptedJury({1: uniform({"secret-id-0": 9, "secret-id-1": 5, "secret-id-2": 3})}, veto={(1, "secret-id-0"): "accuse nommement X de vol"})
    result, _ = run(script)
    c = by_id(result)["secret-id-0"]
    assert c["veto"] == {"judge": "conformite", "reason": "accuse nommement X de vol"}
    assert c["scores"] == {"hook": 9, "standalone": 9}
    assert by_id(result)["secret-id-1"]["veto"] is None


def test_veto_lifted_in_debate_is_not_applied():
    script = ScriptedJury({1: split_notes()}, veto={(1, "secret-id-1"): "risque de diffamation"})
    result, _ = run(script)
    c = by_id(result)["secret-id-1"]
    assert c["veto"] is None
    assert c["trace"]["rounds"][0]["judges"]["conformite"]["veto"] is True


def test_veto_without_reason_is_invalid():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})

    def unmotivated(request):
        answer = script(request)
        if request.usage == "jury_conformite":
            answer["candidates"][0]["veto"] = True
            answer["candidates"][0]["veto_reason"] = ""
        return answer

    fake = FakeBackend([unmotivated] * 5)
    with llm.use_backend(fake), pytest.raises(llm.SchemaError, match="veto"):
        jury.deliberate(candidates(), RUBRIC, config=make_config())


def test_compliance_prompt_excuses_reported_speech_and_lists_real_ban_risks():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    _, fake = run(script)
    prompt = next(c.prompt for c in fake.calls if c.usage == "jury_conformite")
    # regle du propos rapporte : pas de veto sur un propos clivant/polemique tenu
    # par une personnalite publique ou un invite, rapporte tel quel
    assert "rapport" in prompt
    assert "personnalite publique" in prompt or "invite" in prompt
    assert "n'est pas un motif de veto" in prompt or "N'EST PAS un motif de veto" in prompt
    assert "religion" in prompt
    # liste des motifs de veto reserves a un vrai risque de ban
    for motif in (
        "harcelement",
        "mineur identifiable",
        "contenu sexuel",
        "violence graphique gratuite",
        "incitation",
        "diffamation",
        "oeuvre protegee",
    ):
        assert motif in prompt, motif
    # "haine" seule n'est plus un motif generique
    assert "haine ou harcelement" not in prompt


def test_veto_field_in_schema_is_shared_by_the_veto_judges_model_group():
    # Le schema est identique pour tous les juges d'un meme modele (prefixe
    # de prompt commun, TASK-b0fa) : les champs veto/veto_reason y figurent
    # des qu'un juge de ce modele a veto=True, meme pour un juge qui n'en
    # tient pas compte (seul conformite l'exploite, voir _ask). Composition
    # par defaut : "fast" = spectateur + conformite (veto), "strong" = le
    # reste (aucun veto).
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    _, fake = run(script)
    fast_group = {"jury_spectateur", "jury_conformite"}
    for call in fake.calls:
        item = call.schema["properties"]["candidates"]["items"]["properties"]
        assert ("veto" in item) == (call.usage in fast_group), call.usage


# --------------------------------------------------------------------------
# Reponses invalides et quorum
# --------------------------------------------------------------------------


def test_invalid_judge_answer_raises_without_quorum():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})}, raw={(1, "monteur"): "pas du json"})
    with pytest.raises(llm.SchemaError, match="non JSON"):
        run(script)
    assert script.repairs["monteur"] == [1]  # renvoye une fois au modele, encore invalide


def test_judge_answer_repaired_by_the_model_is_kept():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})
    pending = {"monteur"}

    def invalid_once(request):
        answer = script(request)
        judge = request.usage.removeprefix("jury_")
        if judge in pending:
            pending.discard(judge)
            return "pas du json"
        return answer

    fake = FakeBackend([invalid_once] * 12)
    with llm.use_backend(fake):
        result = jury.deliberate(candidates(), RUBRIC, config=make_config(jury_table={"quorum": 4}))

    assert script.repairs["monteur"] == [1]
    assert result["failed"] == []
    assert "monteur" in by_id(result)["secret-id-0"]["trace"]["rounds"][0]["judges"]


def test_missing_candidate_in_answer_is_invalid():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})

    def partial(request):
        answer = script(request)
        if request.usage == "jury_monteur":
            answer["candidates"] = answer["candidates"][:2]
        return answer

    fake = FakeBackend([partial] * 5)
    with llm.use_backend(fake), pytest.raises(llm.SchemaError):
        jury.deliberate(candidates(), RUBRIC, config=make_config())


def test_quorum_tolerates_invalid_answers_and_traces_them():
    script = ScriptedJury(
        {1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})},
        raw={(1, "monteur"): "pas du json"},
    )
    result, _ = run(script, config=make_config(jury_table={"quorum": 4}))
    assert [f["judge"] for f in result["failed"]] == ["monteur"]
    assert result["failed"][0]["round"] == 1
    assert "non JSON" in result["failed"][0]["error"]
    assert script.repairs["monteur"] == [1]
    c = by_id(result)["secret-id-0"]
    assert "monteur" not in c["trace"]["rounds"][0]["judges"]
    assert c["scores"] == {"hook": 7, "standalone": 7}


def test_below_quorum_raises():
    script = ScriptedJury(
        {1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})},
        raw={(1, "monteur"): "pas du json", (1, "avocat"): "{}"},
    )
    with pytest.raises(jury.JuryError, match="quorum"):
        run(script, config=make_config(jury_table={"quorum": 4}))


def test_veto_judge_is_always_required():
    script = ScriptedJury(
        {1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})},
        raw={(1, "conformite"): "pas du json"},
    )
    with pytest.raises(llm.SchemaError):
        run(script, config=make_config(jury_table={"quorum": 3}))


def test_transient_error_is_never_absorbed_by_quorum():
    script = ScriptedJury({1: uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})})

    def flaky(request):
        if request.usage == "jury_monteur":
            raise llm.TransientLLMError("quota")
        return script(request)

    fake = FakeBackend([flaky] * 5)
    with llm.use_backend(fake), pytest.raises(llm.TransientLLMError):
        jury.deliberate(candidates(), RUBRIC, config=make_config(jury_table={"quorum": 3}))


# --------------------------------------------------------------------------
# Configuration invalide
# --------------------------------------------------------------------------


def test_fewer_than_three_judges_is_refused():
    table = {"judges": {name: {"enabled": False} for name in ("monteur", "avocat", "spectateur")}}
    with pytest.raises(jury.JuryError, match="3 juges"):
        jury.deliberate(candidates(), RUBRIC, config=make_config(jury_table=table))


def test_unknown_judge_key_is_refused():
    table = {"judges": {"retention": {"modele": "x"}}}
    with pytest.raises(jury.JuryError, match="modele"):
        jury.deliberate(candidates(), RUBRIC, config=make_config(jury_table=table))


def test_duplicate_candidate_ids_are_refused():
    cands = candidates(2)
    cands[1]["id"] = cands[0]["id"]
    with pytest.raises(jury.JuryError, match="id"):
        jury.deliberate(cands, RUBRIC, config=make_config())


def test_added_judge_takes_part():
    table = {"judges": {"historien": {"perspective": "Historien : " + "x" * 50}}}
    notes = uniform({"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3})
    notes["historien"] = {"secret-id-0": 7, "secret-id-1": 5, "secret-id-2": 3}
    script = ScriptedJury({1: notes})
    result, fake = run(script, config=make_config(jury_table=table))
    assert "jury_historien" in {c.usage for c in fake.calls}
    assert [j["name"] for j in result["judges"]] == JUDGES + ["historien"]


# --------------------------------------------------------------------------
# Integration reelle (optionnelle)
# CLIPPER_CLAUDE_INTEGRATION=1 pytest tests/test_jury.py -k integration
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CLIPPER_CLAUDE_INTEGRATION") != "1",
    reason="integration Claude : definir CLIPPER_CLAUDE_INTEGRATION=1 (consomme du quota)",
)
def test_integration_real_claude_jury():
    rubric = {
        "criteria": {
            "hook": {"weight": 3, "question": "La 1re phrase du clip arrete-t-elle le scroll ?"},
            "standalone": {"weight": 3, "question": "Le clip est-il comprehensible sans le reste de la video ?"},
            "payoff": {"weight": 2, "question": "L'arc est-il complet, avec une fin sur punchline ou revelation ?"},
        },
    }
    cands = [
        {
            "id": "fort",
            "text": "Rockstar vient de confirmer la date : GTA 6 sort le 26 mai, et le trailer 3 arrive "
            "demain. J'ai eu la confirmation par deux sources internes, et franchement je n'y croyais "
            "plus. Donc oui, vous pouvez poser vos congés.",
        },
        {
            "id": "faible",
            "text": "Euh, donc voila, comme je disais tout a l'heure, on va revenir sur ce point plus tard, "
            "attendez je regarde le chat, ok, ok.",
        },
    ]
    result = jury.deliberate(cands, rubric, context="Live d'un streamer francais sur GTA 6.", config=make_config())
    scores = {c["id"]: c["score"] for c in result["candidates"]}
    assert scores["fort"] > scores["faible"]
    assert all(len(c["trace"]["rounds"][0]["judges"]) == 5 for c in result["candidates"])
