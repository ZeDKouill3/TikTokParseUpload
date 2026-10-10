from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipper import jury, jury_coach, llm
from clipper.config import Config
from clipper.llm.fake import FakeBackend

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

RUBRIC = {"criteria": {"hook": {"weight": 1, "question": "Accroche ?"}}}

OLD_RETENTION = "Retention (v0) : juge l'accroche des 3 premieres secondes."
NEW_GOOD = "Retention (v1) : juge l'accroche ET la chute, avec plus de nuance."
SPECTATEUR = "Spectateur cible : tu as 16-30 ans, tu scrolles ton fil TikTok le soir."
CONFORMITE = "Conformite : verifie les risques reels."


# --------------------------------------------------------------------------
# Donnees synthetiques
# --------------------------------------------------------------------------


def make_config(**sections):
    return Config(mode="auto", workspace_dir=Path("workspace"), output_dir=Path("output"), _sections=sections)


def write_journal(entries, path="state/outcomes.jsonl"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def stats_entry(video_id, moment_id, percentile, *, at=None, with_ids=True):
    """Releve mur d'un clip publie (clipper.learning) : rang des vues dans le compte."""
    return {
        "kind": "stats",
        "video_id": video_id if with_ids else None,
        "clip_id": f"{video_id}-{moment_id}",
        "moment_id": moment_id if with_ids else None,
        "stats": {"views": 1000, "views_percentile": percentile},
        "recorded_at": (at or NOW - timedelta(days=1)).isoformat(),
    }


def result_entry(video_id, moment_id, *, qa="passed", at=None):
    """Clip publie : qa + decision vide, vaut passed pour tout clip publie."""
    return {
        "kind": "result",
        "video_id": video_id,
        "clip_id": f"{video_id}-{moment_id}",
        "moment_id": moment_id,
        "qa": {"status": qa, "issues": []},
        "human_decision": None,
        "recorded_at": (at or NOW - timedelta(days=1)).isoformat(),
    }


def trace_for(judge, score):
    return {
        "rounds": [{"round": 1, "judges": {judge: {"scores": {"hook": round(score / 10)}, "score": score, "argument": "..."}}}],
        "revisions": [],
        "dissent": [],
    }


def make_cases(judge="retention", n=6, video_id="v1"):
    """n cas au resultat reel connu (percentile de vues 1.0/0.0 en alternance), avec
    une note passee du juge a l'envers du resultat reel : un rejeu qui
    predit juste doit donc faire mieux que l'ancienne perspective."""
    cases, journal = [], []
    for k in range(n):
        outcome_qa = "passed" if k % 2 == 0 else "rejected"
        journal.append(result_entry(video_id, k))
        journal.append(stats_entry(video_id, k, 1.0 if outcome_qa == "passed" else 0.0))
        wrong_score = 0 if outcome_qa == "passed" else 100
        cases.append(
            {
                "video_id": video_id,
                "moment_id": k,
                "text": f"texte {k}",
                "context": f"[{k * 10}-{k * 10 + 5}] s",
                "trace": trace_for(judge, wrong_score),
            }
        )
    write_journal(journal)
    return cases


def replay_score(prompt: str, k: int) -> int:
    """Score (0-10) qu'un rejeu renvoie pour le cas ``k`` : predit juste
    (matche le resultat pair/impair) sous NEW_GOOD, faux sinon (meme
    comportement que la trace passee, pour representer une perspective qui
    n'a pas change)."""
    matches = NEW_GOOD in prompt
    correct = (k % 2 == 0) == matches
    return 10 if correct else 0


def make_backend(lesson_response, *, judge="retention"):
    def _respond(request):
        if request.usage == "coach":
            return lesson_response
        m = re.search(r"texte (\d+)", request.prompt)
        assert m, f"prompt de rejeu sans candidat identifiable : {request.prompt!r}"
        k = int(m.group(1))
        return {"scores": {"hook": replay_score(request.prompt, k)}}

    return _respond


# --------------------------------------------------------------------------
# Ecrit une proposition adoptee (le rejeu fait mieux)
# --------------------------------------------------------------------------


def test_writes_versioned_prompt_when_replay_improves(isolated_cwd):
    cases = make_cases(n=6)
    judges = {"retention": OLD_RETENTION, "spectateur": SPECTATEUR}
    fake = FakeBackend([make_backend({"perspective": NEW_GOOD, "justification": "predit mieux les cas rejoues"})])

    with llm.use_backend(fake):
        results = jury_coach.propose(cases, RUBRIC, judges, config=make_config(), now=NOW)

    by_judge = {r["judge"]: r for r in results}
    retention = by_judge["retention"]
    assert retention["accepted"] is True
    assert retention["version"] == 1
    assert retention["metric"]["before"] == pytest.approx(1.0)
    assert retention["metric"]["after"] == pytest.approx(0.0)

    path = Path("prompts/jury/retention/v1.md")
    assert path == Path(retention["path"])
    content = path.read_text(encoding="utf-8")
    assert NEW_GOOD in content
    assert "predit mieux les cas rejoues" in content


def test_skips_judge_without_enough_known_outcomes(isolated_cwd):
    cases = make_cases(n=6)  # trace ne porte que le juge "retention"
    judges = {"retention": OLD_RETENTION, "spectateur": SPECTATEUR}
    fake = FakeBackend([make_backend({"perspective": NEW_GOOD, "justification": "..."})])

    with llm.use_backend(fake):
        results = jury_coach.propose(cases, RUBRIC, judges, config=make_config(), now=NOW)

    spectateur = next(r for r in results if r["judge"] == "spectateur")
    assert spectateur["accepted"] is False
    assert spectateur["version"] is None
    assert not Path("prompts/jury/spectateur").exists()


# --------------------------------------------------------------------------
# Refus : ne predit pas mieux en rejeu
# --------------------------------------------------------------------------


def test_rejects_proposal_that_does_not_predict_better(isolated_cwd):
    cases = make_cases(n=6)
    judges = {"retention": OLD_RETENTION, "spectateur": SPECTATEUR}

    def _respond(request):
        if request.usage == "coach":
            return {"perspective": "Retention (mauvaise) : ne change rien de fond.", "justification": "..."}
        m = re.search(r"texte (\d+)", request.prompt)
        k = int(m.group(1))
        # Toujours a l'envers du resultat, ancienne comme nouvelle perspective.
        return {"scores": {"hook": 10 if k % 2 == 0 else 0}}

    fake = FakeBackend([_respond])

    with llm.use_backend(fake):
        results = jury_coach.propose(cases, RUBRIC, judges, config=make_config(), now=NOW)

    retention = next(r for r in results if r["judge"] == "retention")
    assert retention["accepted"] is False
    assert retention["reason"] == "ne predit pas mieux en rejeu"
    assert not Path("prompts/jury/retention").exists()


# --------------------------------------------------------------------------
# Refus : rapproche deux perspectives
# --------------------------------------------------------------------------


def test_rejects_proposal_too_similar_to_another_judge(isolated_cwd):
    cases = make_cases(n=6)
    judges = {"retention": OLD_RETENTION, "spectateur": SPECTATEUR}
    fake = FakeBackend([make_backend({"perspective": SPECTATEUR, "justification": "..."})])

    with llm.use_backend(fake):
        results = jury_coach.propose(cases, RUBRIC, judges, config=make_config(), now=NOW)

    retention = next(r for r in results if r["judge"] == "retention")
    assert retention["accepted"] is False
    assert "spectateur" in retention["reason"]
    assert not Path("prompts/jury/retention").exists()
    # Le rejeu (couteux) n'est jamais tente pour une proposition deja refusee.
    assert all(c.usage != "jury_retention" for c in fake.calls)


# --------------------------------------------------------------------------
# Refus : plafond de lecons par juge
# --------------------------------------------------------------------------


def test_respects_lessons_cap_per_judge(isolated_cwd):
    cases = make_cases(n=6)
    judges = {"retention": OLD_RETENTION}
    judge_dir = Path("prompts/jury/retention")
    judge_dir.mkdir(parents=True)
    (judge_dir / "v1.md").write_text("# v1", encoding="utf-8")
    (judge_dir / "v2.md").write_text("# v2", encoding="utf-8")
    fake = FakeBackend([make_backend({"perspective": NEW_GOOD, "justification": "..."})])
    config = make_config(jury_coach={"max_lessons_per_judge": 2})

    with llm.use_backend(fake):
        results = jury_coach.propose(cases, RUBRIC, judges, config=config, now=NOW)

    retention = next(r for r in results if r["judge"] == "retention")
    assert retention["accepted"] is False
    assert retention["reason"] == "plafond de lecons atteint"
    assert fake.calls == []  # jamais demande de retouche une fois le plafond atteint


def test_writes_next_free_version_number(isolated_cwd):
    cases = make_cases(n=6)
    judges = {"retention": OLD_RETENTION}
    judge_dir = Path("prompts/jury/retention")
    judge_dir.mkdir(parents=True)
    (judge_dir / "v1.md").write_text("# v1", encoding="utf-8")
    fake = FakeBackend([make_backend({"perspective": NEW_GOOD, "justification": "..."})])

    with llm.use_backend(fake):
        results = jury_coach.propose(cases, RUBRIC, judges, config=make_config(), now=NOW)

    retention = next(r for r in results if r["judge"] == "retention")
    assert retention["version"] == 2
    assert Path("prompts/jury/retention/v2.md").exists()


# --------------------------------------------------------------------------
# Le juge conformite est toujours exclu
# --------------------------------------------------------------------------


def test_conformite_judge_is_never_coached(isolated_cwd):
    cases = make_cases(judge="conformite", n=6)
    judges = {"conformite": CONFORMITE, "retention": OLD_RETENTION}
    fake = FakeBackend([make_backend({"perspective": NEW_GOOD, "justification": "..."})])

    with llm.use_backend(fake):
        results = jury_coach.propose(cases, RUBRIC, judges, config=make_config(), now=NOW)

    assert "conformite" not in [r["judge"] for r in results]
    assert all("conformite" not in (c.usage or "") for c in fake.calls)
    assert not Path("prompts/jury/conformite").exists()


# --------------------------------------------------------------------------
# Resultat reel = vues (stats), jamais qa/decision seuls
# --------------------------------------------------------------------------


def real_outcomes(journal):
    return jury_coach._real_outcomes(journal, NOW - timedelta(days=90), "views_percentile")


def test_published_clips_with_different_percentiles_have_different_outcomes():
    out = real_outcomes([
        result_entry("v1", 0), stats_entry("v1", 0, 0.9),
        result_entry("v1", 1), stats_entry("v1", 1, 0.2),
    ])
    assert out == {("v1", 0): pytest.approx(0.9), ("v1", 1): pytest.approx(0.2)}


def test_published_clip_without_stats_is_excluded_not_one():
    out = real_outcomes([result_entry("v1", 0), result_entry("v1", 1), stats_entry("v1", 1, 0.4)])
    assert out == {("v1", 1): pytest.approx(0.4)}


def test_stats_without_percentile_or_ids_or_outside_window_are_excluded():
    no_metric = stats_entry("v1", 0, 0.5)
    no_metric["stats"]["views_percentile"] = None
    old = stats_entry("v1", 1, 0.5, at=NOW - timedelta(days=200))
    out = real_outcomes([no_metric, old, stats_entry("v1", 2, 0.5, with_ids=False)])
    assert out == {}


def test_case_with_only_qa_result_is_not_coached_on_a_constant(isolated_cwd):
    cases = make_cases(n=6)
    Path("state/outcomes.jsonl").write_text(
        "".join(json.dumps(result_entry("v1", k)) + "\n" for k in range(6)), encoding="utf-8")
    fake = FakeBackend([make_backend({"perspective": NEW_GOOD, "justification": "..."})])
    with llm.use_backend(fake):
        results = jury_coach.propose(cases, RUBRIC, {"retention": OLD_RETENTION}, config=make_config(), now=NOW)
    assert results[0]["accepted"] is False
    assert results[0]["reason"] == "pas assez de cas connus"


def test_replay_uses_the_model_of_the_judge_like_the_real_judgment(isolated_cwd):
    cases = make_cases(n=6)
    judges = {"retention": OLD_RETENTION, "spectateur": SPECTATEUR}
    fake = FakeBackend([make_backend({"perspective": NEW_GOOD, "justification": "..."})])

    with llm.use_backend(fake):
        config = make_config()
        jury_coach.propose(cases, RUBRIC, judges, config=config, now=NOW,
                           judge_configs={"retention": jury._JudgeConfig(config, "jury_retention", "strong")})

    replays = [c for c in fake.calls if c.usage == "jury_retention"]
    assert len(replays) == 10 and {c.model for c in replays} == {"opus"}  # strong -> opus, pas le palier fast (sonnet)


def test_propose_logs_its_calls_in_the_given_usage_log_only(isolated_cwd):
    cases = make_cases(n=6)
    video_log = Path("workspace/v1/llm_usage.jsonl")
    own = Path("state/learning/llm_usage.jsonl")
    fake = FakeBackend([make_backend({"perspective": NEW_GOOD, "justification": "..."})])

    with llm.use_backend(fake), llm.usage_log(video_log):
        jury_coach.propose(cases, RUBRIC, {"retention": OLD_RETENTION}, config=make_config(), now=NOW, usage_log_path=own)

    assert not video_log.exists()
    usages = {json.loads(line)["usage"] for line in own.read_text(encoding="utf-8").splitlines()}
    assert usages == {"coach", "jury_retention"}


def test_coach_reads_the_metric_from_the_calibration_setting():
    entry = stats_entry("v1", 0, 0.9)
    entry["stats"]["watched_full"] = 0.2
    out = jury_coach._real_outcomes([entry], NOW - timedelta(days=90), "watched_full")
    assert out == {("v1", 0): pytest.approx(0.2)}
    assert jury_coach._real_outcomes([entry], NOW - timedelta(days=90), "views_percentile") == {("v1", 0): pytest.approx(0.9)}


def test_propose_learns_on_the_configured_metric(isolated_cwd):
    cases = make_cases(n=6)  # views_percentile 1.0/0.0, predictions a l'envers
    entries = Path("state/outcomes.jsonl").read_text(encoding="utf-8").splitlines()
    rewritten = []
    for line in entries:
        e = json.loads(line)
        if e["kind"] == "stats":
            e["stats"]["watched_full"] = 1.0 - e["stats"]["views_percentile"]  # verite inversee
        rewritten.append(json.dumps(e))
    Path("state/outcomes.jsonl").write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    fake = FakeBackend([make_backend({"perspective": NEW_GOOD, "justification": "x"})])

    with llm.use_backend(fake):
        results = jury_coach.propose(cases, RUBRIC, {"retention": OLD_RETENTION}, config=make_config(
            jury_calibration={"stats_metric": "watched_full"}), now=NOW)

    assert results[0]["accepted"] is False  # sur watched_full, l'ancienne perspective predit deja juste
    assert results[0]["metric"]["before"] == pytest.approx(0.0)
