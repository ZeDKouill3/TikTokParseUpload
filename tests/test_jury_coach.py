from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipper import jury_coach, llm
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


def result_entry(video_id, moment_id, *, qa="passed", at=None):
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
    """n cas au resultat reel connu (qa passed/rejected en alternance), avec
    une note passee du juge a l'envers du resultat reel : un rejeu qui
    predit juste doit donc faire mieux que l'ancienne perspective."""
    cases, journal = [], []
    for k in range(n):
        outcome_qa = "passed" if k % 2 == 0 else "rejected"
        journal.append(result_entry(video_id, k, qa=outcome_qa))
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
