from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipper import jury, llm
from clipper.config import Config
from clipper.llm.fake import FakeBackend

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
JUDGES = ["retention", "spectateur", "monteur", "avocat", "conformite"]


# --------------------------------------------------------------------------
# Donnees synthetiques
# --------------------------------------------------------------------------


def make_config(calibration=None, jury_table=None):
    sections = {"outcomes": {"journal_path": "state/outcomes.jsonl"}}
    if calibration is not None:
        sections["jury_calibration"] = calibration
    if jury_table is not None:
        sections["jury"] = jury_table
    return Config(mode="auto", workspace_dir=Path("workspace"), output_dir=Path("output"), _sections=sections)


def candidate(scores_by_judge):
    """Entree de deliberate()["candidates"] reduite a la trace : un tour,
    score final de chaque juge ; le juge conformite porte la cle veto."""
    judges = {}
    for name, score in scores_by_judge.items():
        entry = {"scores": {}, "score": score, "argument": "..."}
        if name == "conformite":
            entry["veto"] = False
            entry["veto_reason"] = ""
        judges[name] = entry
    return {"id": "x", "trace": {"rounds": [{"round": 1, "judges": judges}], "revisions": [], "dissent": []}}


def write_journal(entries):
    path = Path("state/outcomes.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def result_entry(video_id, moment_id, clip_id, *, qa="passed", human=None, at=NOW - timedelta(days=1)):
    return {
        "kind": "result", "video_id": video_id, "clip_id": clip_id, "moment_id": moment_id,
        "qa": {"status": qa, "issues": []}, "human_decision": human, "recorded_at": at.isoformat(),
    }


def stats_entry(clip_id, watched_full, *, at=NOW - timedelta(days=1)):
    return {
        "kind": "stats", "video_id": None, "clip_id": clip_id, "moment_id": None,
        "stats": {"views": 1000, "retention_3s": 0.5, "watched_full": watched_full, "shares": 3, "date": "2026-09-20"},
        "recorded_at": at.isoformat(),
    }


def scenario(n=10, video_id="v1", at=NOW - timedelta(days=1)):
    """n moments ; le resultat reel (watched_full) croit avec k. retention et
    conformite notent dans le meme sens (bons predicteurs), avocat a
    l'envers (mauvais), spectateur et monteur au hasard fixe."""
    noise = [55, 20, 80, 35, 65, 10, 90, 45, 30, 70, 60, 25]
    traces, journal = [], []
    for k in range(n):
        clip_id = f"{video_id}-{k:02d}"
        journal.append(result_entry(video_id, k, clip_id, at=at))
        journal.append(stats_entry(clip_id, round(k / n, 3), at=at))
        scores = {
            "retention": 10 * k,
            "spectateur": noise[k % len(noise)],
            "monteur": noise[(k + 5) % len(noise)],
            "avocat": 100 - 10 * k,
            "conformite": 10 * k,
        }
        traces.append({"video_id": video_id, "moment_id": k, "candidate": candidate(scores)})
    write_journal(journal)
    return traces


def calibrate(traces, **settings):
    from clipper import jury_calibration

    return jury_calibration.calibrate(traces, config=make_config(settings), now=NOW)


def weights(result):
    return {name: j["weight"] for name, j in result["judges"].items()}


# --------------------------------------------------------------------------
# Poids : bon predicteur > 1, mauvais < 1
# --------------------------------------------------------------------------


def test_good_predictor_gets_weight_above_one(isolated_cwd):
    result = calibrate(scenario(), min_clips=5)

    assert weights(result)["retention"] > 1


def test_bad_predictor_gets_weight_below_one(isolated_cwd):
    result = calibrate(scenario(), min_clips=5)

    assert weights(result)["avocat"] < 1


def test_agreement_is_reported_per_judge(isolated_cwd):
    result = calibrate(scenario(), min_clips=5)

    assert result["judges"]["retention"]["agreement"] == pytest.approx(1.0)
    assert result["judges"]["avocat"]["agreement"] == pytest.approx(-1.0)
    assert result["judges"]["retention"]["clips"] == 10


def test_qa_and_human_decisions_are_real_outcomes(isolated_cwd):
    # Sans statistiques : qa rejete et decision humaine rejetee = mauvais resultat.
    traces, journal = [], []
    for k in range(6):
        good = k >= 3
        journal.append(result_entry("v1", k, f"c{k}", qa="passed" if good else "rejected",
                                    human="accepted" if good else "rejected"))
        traces.append({"video_id": "v1", "moment_id": k, "candidate": candidate(
            {"retention": 80 if good else 20, "spectateur": 20 if good else 80, "monteur": 50,
             "avocat": 50, "conformite": 50})})
    write_journal(journal)

    result = calibrate(traces, min_clips=5)

    assert weights(result)["retention"] > 1
    assert weights(result)["spectateur"] < 1


# --------------------------------------------------------------------------
# Bornes (defaut 0,5 a 1,5, configurables)
# --------------------------------------------------------------------------


def test_default_bounds_are_half_to_one_and_a_half(isolated_cwd):
    result = calibrate(scenario(), min_clips=5, smoothing=0.0)

    assert weights(result)["retention"] == pytest.approx(1.5)
    assert weights(result)["avocat"] == pytest.approx(0.5)


def test_weights_stay_within_configured_bounds(isolated_cwd):
    result = calibrate(scenario(), min_clips=5, smoothing=0.0, min_weight=0.8, max_weight=1.2)

    assert weights(result)["retention"] == pytest.approx(1.2)
    assert weights(result)["avocat"] == pytest.approx(0.8)
    assert all(0.8 <= w <= 1.2 for w in weights(result).values())


def test_invalid_bounds_are_an_error(isolated_cwd):
    from clipper.jury_calibration import CalibrationError

    with pytest.raises(CalibrationError, match="min_weight"):
        calibrate(scenario(), min_weight=1.2, max_weight=0.8)


# --------------------------------------------------------------------------
# Minimum de clips : sinon poids 1
# --------------------------------------------------------------------------


def test_below_min_clips_every_weight_is_one(isolated_cwd):
    result = calibrate(scenario(n=4), min_clips=5, smoothing=0.0)

    assert weights(result) == {name: 1.0 for name in JUDGES}
    assert result["judges"]["retention"]["clips"] == 4


def test_at_min_clips_the_weight_moves(isolated_cwd):
    result = calibrate(scenario(n=5), min_clips=5, smoothing=0.0)

    assert weights(result)["retention"] == pytest.approx(1.5)


def test_moments_without_outcome_do_not_count(isolated_cwd):
    traces = scenario(n=5)
    # Traces sans aucun resultat au journal : ne comptent pas comme clips.
    traces += [{"video_id": "v2", "moment_id": k, "candidate": candidate({j: 50 for j in JUDGES})} for k in range(5)]

    result = calibrate(traces, min_clips=6)

    assert result["judges"]["retention"]["clips"] == 5
    assert weights(result)["retention"] == 1.0


# --------------------------------------------------------------------------
# Conformite : toujours poids 1
# --------------------------------------------------------------------------


def test_conformity_judge_always_keeps_weight_one(isolated_cwd):
    # conformite note exactement comme retention (bon predicteur), et pourtant.
    result = calibrate(scenario(), min_clips=5, smoothing=0.0)

    assert weights(result)["conformite"] == 1.0
    assert weights(result)["retention"] == pytest.approx(1.5)


def test_conformity_weight_ignores_a_previous_file(isolated_cwd):
    path = Path("state/jury_weights.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"computed_at": NOW.isoformat(), "judges": {"conformite": {"weight": 1.4}}}))

    result = calibrate(scenario(), min_clips=5)

    assert weights(result)["conformite"] == 1.0


# --------------------------------------------------------------------------
# Fenetre configuree, lissage
# --------------------------------------------------------------------------


def test_outcomes_outside_the_window_are_ignored(isolated_cwd):
    traces = scenario(n=10, at=NOW - timedelta(days=200))

    result = calibrate(traces, min_clips=5, window_days=30)

    assert result["judges"]["retention"]["clips"] == 0
    assert weights(result)["retention"] == 1.0


def test_smoothing_blends_with_previous_weight(isolated_cwd):
    path = Path("state/jury_weights.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"computed_at": NOW.isoformat(), "judges": {"retention": {"weight": 0.5}}}))

    result = calibrate(scenario(), min_clips=5, smoothing=0.5)

    # cible 1,5 (accord parfait), precedent 0,5 : moitie-moitie.
    assert weights(result)["retention"] == pytest.approx(1.0)
    assert result["judges"]["retention"]["previous"] == 0.5


def test_first_calibration_is_smoothed_from_one(isolated_cwd):
    result = calibrate(scenario(), min_clips=5, smoothing=0.5)

    assert weights(result)["retention"] == pytest.approx(1.25)
    assert weights(result)["avocat"] == pytest.approx(0.75)


# --------------------------------------------------------------------------
# Fichier state/jury_weights.json, date
# --------------------------------------------------------------------------


def test_dated_weights_are_written_to_state(isolated_cwd):
    result = calibrate(scenario(), min_clips=5)

    written = json.loads((isolated_cwd / "state" / "jury_weights.json").read_text(encoding="utf-8"))
    assert written == result
    assert written["computed_at"] == NOW.isoformat()
    assert written["judges"]["retention"]["weight"] == weights(result)["retention"]


def test_weights_path_is_configurable(isolated_cwd):
    calibrate(scenario(), min_clips=5, weights_path="elsewhere/w.json")

    assert (isolated_cwd / "elsewhere" / "w.json").exists()


def test_config_table_is_accepted_by_load_config(isolated_cwd):
    from clipper.config import load_config

    Path("config.toml").write_text("[jury_calibration]\nmin_clips = 30\nwindow_days = 60\n", encoding="utf-8")

    assert load_config().section("jury_calibration")["min_clips"] == 30


# --------------------------------------------------------------------------
# Statistiques CSV : seulement clip_id, reliees par les autres entrees
# --------------------------------------------------------------------------


def test_stats_are_linked_through_result_entries_with_same_clip_id(isolated_cwd):
    from clipper import outcomes

    traces = []
    for k in range(6):
        outcomes.record(video_id="v1", clip_id=f"v1-{k:02d}", moment_id=k, qa={"status": "passed", "issues": []})
        traces.append({"video_id": "v1", "moment_id": k, "candidate": candidate(
            {"retention": 10 * k, "spectateur": 100 - 10 * k, "monteur": 50, "avocat": 50, "conformite": 50})})
    csv_path = isolated_cwd / "stats.csv"
    csv_path.write_text(
        "clip_id,views,retention_3s,watched_full,shares,date\n"
        + "".join(f"v1-{k:02d},100,0.5,{k / 10},1,2026-09-20\n" for k in range(6)),
        encoding="utf-8",
    )
    outcomes.import_stats(csv_path)

    from clipper import jury_calibration

    result = jury_calibration.calibrate(
        traces, config=make_config({"min_clips": 5}), now=datetime.now(timezone.utc) + timedelta(minutes=1)
    )

    # qa identique partout : seul watched_full, relie par clip_id, departage.
    assert weights(result)["retention"] > 1
    assert weights(result)["spectateur"] < 1


def test_ambiguous_clip_id_stats_are_ignored_and_reported(isolated_cwd, caplog):
    traces = scenario(n=6)
    # "00" est porte par deux videos : impossible d'attribuer la statistique.
    write_journal([result_entry("v8", 0, "dup"), result_entry("v9", 0, "dup"), stats_entry("dup", 0.9)])

    result = calibrate(traces, min_clips=5)

    assert result["ignored_stats"] == [{"clip_id": "dup", "reason": "ambiguous", "matches": [["v8", 0], ["v9", 0]]}]
    assert "dup" in caplog.text


def test_unlinked_stats_are_ignored_and_reported(isolated_cwd):
    traces = scenario(n=6)
    write_journal([stats_entry("orphan", 0.9)])

    result = calibrate(traces, min_clips=5)

    assert result["ignored_stats"] == [{"clip_id": "orphan", "reason": "unlinked", "matches": []}]


def test_unknown_human_decision_is_an_error(isolated_cwd):
    from clipper.jury_calibration import CalibrationError

    traces = scenario(n=6)
    write_journal([result_entry("v1", 0, "v1-00", human="peut-etre")])

    with pytest.raises(CalibrationError, match="peut-etre"):
        calibrate(traces, min_clips=5)


def test_final_round_score_is_the_judge_score(isolated_cwd):
    # Un candidat debattu : c'est la note du tour 2 qui compte.
    traces = scenario(n=6)
    for t in traces:
        rounds = t["candidate"]["trace"]["rounds"]
        r2 = json.loads(json.dumps(rounds[0]))
        r2["round"] = 2
        r2["judges"]["retention"]["score"], r2["judges"]["avocat"]["score"] = (
            r2["judges"]["avocat"]["score"], r2["judges"]["retention"]["score"])
        rounds.append(r2)

    result = calibrate(traces, min_clips=5)

    assert weights(result)["retention"] < 1
    assert weights(result)["avocat"] > 1


# --------------------------------------------------------------------------
# clipper.jury applique les poids (mediane ponderee) quand le fichier existe
# --------------------------------------------------------------------------


RUBRIC = {"criteria": {"hook": {"weight": 1, "question": "Accroche ?"}}}
FIXED = {"retention": 9, "spectateur": 8, "conformite": 5, "monteur": 2, "avocat": 1}


def fixed_jury(request):
    judge = request.usage.removeprefix("jury_")
    refs = re.findall(r"^### (C\d+)$", request.prompt, re.M)
    answer = []
    for ref in refs:
        item = {"ref": ref, "argument": "arg", "scores": {"hook": FIXED[judge]}}
        if judge == "conformite":
            item["veto"], item["veto_reason"] = False, ""
        answer.append(item)
    return {"candidates": answer}


def deliberate():
    fake = FakeBackend([fixed_jury] * 10)
    with llm.use_backend(fake):
        return jury.deliberate([{"id": "a", "text": "texte"}], RUBRIC, config=make_config(jury_table={"threshold": 100}))


def write_weights(ws, path="state/jury_weights.json"):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"computed_at": NOW.isoformat(), "judges": {n: {"weight": w} for n, w in ws.items()}}))


def test_jury_without_weights_file_uses_plain_median(isolated_cwd):
    result = deliberate()

    assert result["candidates"][0]["scores"] == {"hook": 5}
    assert result["candidates"][0]["score"] == 50.0


def test_jury_applies_weighted_median_when_file_exists(isolated_cwd):
    write_weights({"retention": 1.5, "spectateur": 1.5, "monteur": 0.5, "avocat": 0.5, "conformite": 1.0})

    result = deliberate()

    # poids cumules (1 2 5 8 9) : 0,5 1,0 2,0 3,5 5,0 ; moitie 2,5 atteinte a 8.
    assert result["candidates"][0]["scores"] == {"hook": 8}
    assert result["candidates"][0]["score"] == 80.0
    assert result["weights"]["retention"] == 1.5


def test_jury_weight_defaults_to_one_for_uncalibrated_judge(isolated_cwd):
    write_weights({"avocat": 1.5, "monteur": 1.5})

    result = deliberate()

    # 1 (1,5) 2 (1,5) 5 (1) 8 (1) 9 (1) : total 6, moitie 3 atteinte a 2, pile a la frontiere -> (2+5)/2.
    assert result["candidates"][0]["scores"] == {"hook": 3.5}
    assert result["weights"]["retention"] == 1.0


def test_jury_refuses_a_calibrated_conformity_weight(isolated_cwd):
    write_weights({"conformite": 1.3})

    with pytest.raises(jury.JuryError, match="conformite"):
        deliberate()


def test_jury_refuses_a_malformed_weights_file(isolated_cwd):
    p = Path("state/jury_weights.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{pas du json")

    with pytest.raises(jury.JuryError, match="jury_weights"):
        deliberate()


def test_jury_reads_the_configured_weights_path(isolated_cwd):
    write_weights({"retention": 1.5, "spectateur": 1.5, "monteur": 0.5, "avocat": 0.5}, path="w/j.json")

    fake = FakeBackend([fixed_jury] * 10)
    config = Config(mode="auto", workspace_dir=Path("workspace"), output_dir=Path("output"),
                    _sections={"jury": {"threshold": 100}, "jury_calibration": {"weights_path": "w/j.json"}})
    with llm.use_backend(fake):
        result = jury.deliberate([{"id": "a", "text": "texte"}], RUBRIC, config=config)

    assert result["candidates"][0]["scores"] == {"hook": 8}
