"""Candidats d'action dans l'etape moments (TASK-68b6, SPEC-b0f3 R10-R14) :
[moments] candidates = "transcript+action", meme proposeur, meme jury, meme
grille. Sans reseau : FakeBackend seulement."""
from __future__ import annotations

import json
import re

import pytest

from clipper import llm
from clipper.llm.fake import FakeBackend

from test_moments import (  # noqa: F401  (fixtures et aides reutilisees)
    BORDER, GOOD, LOW_EMOTION, META, TEST_RUBRIC, VIDEO_ID, WEAK, _rubric_with_gate, auto_config, jury_notes,
    make_config, make_transcript, moment, read_moments, rubric_path, spans, video_dir, with_jury,
)

PLUS = "transcript+action"
GATE = '[gate]\ncriterion = "emotion"\nmin = 5\n'


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def frame(timecode, description="un combat", action_type="combat", intensity=5):
    return {
        "timecode": timecode, "path": f"scenes/f{timecode:g}.jpg", "description": description,
        "action_type": action_type, "intensity": intensity,
    }


def passage(start, end, *, id="a0", score=0.8, frames=None, speech_ratio=0.0, peaks=4, cuts=6):
    frames = [frame(start + 5, "un combat rapproche", "combat", 8)] if frames is None else frames
    return {
        "id": id, "start": start, "end": end, "duration": round(end - start, 2), "score": score,
        "signals": {
            "audio_peaks": peaks, "audio_peak_max_db": 12.5, "scene_cuts": cuts, "scene_cuts_ratio": 2.5,
            "speech_ratio": speech_ratio,
        },
        "frames": frames, "frames_missing": not frames,
    }


def write_action(video_dir, *passages, enabled=True):
    data = {"video_id": VIDEO_ID, "enabled": enabled, "passages": list(passages), "rejected": [],
            "llm_calls": 0, "images_sent": 0}
    (video_dir / "action.json").write_text(json.dumps(data), encoding="utf-8")


def mute(video_dir, first, last):
    """Retire de la transcription les phrases first..last (passage sans parole)."""
    t = make_transcript()
    t["segments"] = [s for s in t["segments"] if not first <= s["id"] <= last]
    (video_dir / "transcript.json").write_text(json.dumps(t), encoding="utf-8")


def rate(scores, why="il se passe quelque chose"):
    """Reponse du tour de comparaison pour un seul candidat d'action."""
    return {"moments": [{"id": 0, "justification": why, "scores": dict(scores)}]}


def go(tmp_path, rubric, responses, config=None, **moments):
    from clipper.moments import run as run_moments

    fake = FakeBackend(responses)
    config = config or make_config(tmp_path, rubric, **{"candidates": PLUS, **moments})
    with llm.use_backend(fake):
        run_moments(VIDEO_ID, tmp_path / "workspace", config=config)
    return fake


def judge_by_marker(grids):
    """Juge factice qui reconnait un candidat a un fragment de son bloc
    (la parole d'un candidat d'action n'est pas « motK_0 ») ;
    ``grids`` : {fragment: grille}."""

    def answer(request):
        judge = request.usage.removeprefix("jury_")
        item = request.schema["properties"]["candidates"]["items"]["properties"]
        blocks = dict(re.findall(r"### (C\d+)\n(.*?)(?=\n### C|\Z)", request.prompt, re.S))
        out = []
        for ref in item["ref"]["enum"]:
            grid = next(g for marker, g in grids.items() if marker in blocks[ref])
            entry = {"ref": ref, "argument": f"{judge} sur {ref}", "scores": dict(grid), "confidence": 80}
            if "veto" in item:
                entry["veto"], entry["veto_reason"] = False, ""
            out.append(entry)
        return {"candidates": out}

    return answer


# --------------------------------------------------------------------------
# R10 : reglage et erreurs
# --------------------------------------------------------------------------


def test_defaults_keep_the_transcript_only_behaviour():
    from clipper.moments import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["candidates"] == "transcript"
    assert CONFIG_DEFAULTS["action_snap_seconds"] == 3


def test_unknown_candidates_value_is_a_moments_error_and_writes_nothing(tmp_path, video_dir, rubric_path):
    from clipper.moments import MomentsError

    with pytest.raises(MomentsError, match=r"\[moments\] candidates invalide.*transcript\+action"):
        go(tmp_path, rubric_path, [], candidates="action")
    assert not (video_dir / "moments.json").exists()


def test_plus_without_action_json_is_an_error_naming_the_file(tmp_path, video_dir, rubric_path):
    from clipper.moments import MomentsError

    fake = FakeBackend([])
    with llm.use_backend(fake), pytest.raises(MomentsError, match=r"action\.json"):
        from clipper.moments import run as run_moments

        run_moments(VIDEO_ID, tmp_path / "workspace", config=make_config(tmp_path, rubric_path, candidates=PLUS))
    assert fake.calls == []
    assert not (video_dir / "moments.json").exists()


def test_plus_with_a_disabled_action_step_is_an_error_naming_the_setting(tmp_path, video_dir, rubric_path):
    from clipper.moments import MomentsError

    write_action(video_dir, enabled=False)
    with pytest.raises(MomentsError, match=r"\[action\] enabled"):
        go(tmp_path, rubric_path, [])
    assert not (video_dir / "moments.json").exists()


def test_invalid_snap_seconds_is_a_moments_error(tmp_path, video_dir, rubric_path):
    from clipper.moments import MomentsError

    write_action(video_dir)
    with pytest.raises(MomentsError, match="action_snap_seconds"):
        go(tmp_path, rubric_path, [], action_snap_seconds=-1)


# --------------------------------------------------------------------------
# R11 : un passage devient un candidat
# --------------------------------------------------------------------------


def test_a_passage_without_speech_becomes_a_candidate_with_the_frame_description_as_hook(
    tmp_path, video_dir, rubric_path
):
    mute(video_dir, 20, 39)  # plus de parole de 100 s a 200 s
    write_action(video_dir, passage(120.0, 150.0, frames=[frame(125.0, "un tir", "combat", 4),
                                                         frame(140.0, "une explosion", "mort", 9)]))

    go(tmp_path, rubric_path, [{"moments": []}, rate(GOOD)])

    data = read_moments(video_dir)
    [m] = data["moments"]
    assert (m["start"], m["end"], m["format"], m["parts"]) == (120.0, 150.0, "single", [])
    assert m["hook_text"] == "une explosion"
    assert m["source"] == "action"
    assert m["scores"] == GOOD


def test_a_passage_straddling_a_sentence_is_snapped_within_the_tolerance(tmp_path, video_dir, rubric_path):
    write_action(video_dir, passage(9.0, 45.9))

    go(tmp_path, rubric_path, [{"moments": []}, rate(GOOD)])

    [m] = read_moments(video_dir)["moments"]
    assert (m["start"], m["end"]) == (10.25, 44.65)
    assert m["hook_text"] == "mot2_0 mot2_1 mot2_2 mot2_3 mot2_4."


def test_a_bound_farther_than_the_snap_distance_is_kept_as_it_is(tmp_path, video_dir, rubric_path):
    write_action(video_dir, passage(12.0, 47.5))

    go(tmp_path, rubric_path, [{"moments": []}, rate(GOOD)], action_snap_seconds=1.0)

    [m] = read_moments(video_dir)["moments"]
    assert (m["start"], m["end"]) == (12.0, 47.5)
    assert m["hook_text"].startswith("mot3_0")  # premiere phrase entierement incluse


def test_leading_connectors_are_removed_from_an_action_candidate(tmp_path, video_dir, rubric_path):
    t = make_transcript()
    t["segments"][2]["words"][0]["word"] = " Donc"
    (video_dir / "transcript.json").write_text(json.dumps(t), encoding="utf-8")
    write_action(video_dir, passage(10.0, 44.9))

    go(tmp_path, rubric_path, [{"moments": []}, rate(GOOD)])

    [m] = read_moments(video_dir)["moments"]
    assert m["start"] == 11.15  # le mot qui suit « Donc »
    assert m["hook_text"] == "mot2_1 mot2_2 mot2_3 mot2_4."


def test_a_passage_longer_than_single_max_is_rejected_for_duration(tmp_path, video_dir, rubric_path):
    write_action(video_dir, passage(50.0, 150.0))

    fake = go(tmp_path, rubric_path, [{"moments": []}])

    data = read_moments(video_dir)
    assert data["moments"] == []
    [r] = data["rejected"]
    assert r["reason"].startswith("duree 99.4 s hors bornes single")
    assert r["source"] == "action"
    assert len(fake.calls) == 1  # aucun candidat d'action a noter : pas d'appel de plus


def test_a_passage_over_a_sponsorblock_segment_is_rejected(tmp_path, video_dir, rubric_path):
    write_action(video_dir, passage(205.0, 235.0))

    go(tmp_path, rubric_path, [{"moments": []}])

    [r] = read_moments(video_dir)["rejected"]
    assert "SponsorBlock sponsor" in r["reason"]
    assert r["source"] == "action"


def test_a_passage_identical_to_a_transcript_candidate_is_not_duplicated(tmp_path, video_dir, rubric_path):
    write_action(video_dir, passage(10.0, 45.0))

    fake = go(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65, GOOD)]}])

    data = read_moments(video_dir)
    assert [(m["start"], m["end"], m["source"]) for m in data["moments"]] == [(10.25, 44.65, "transcript")]
    assert len(fake.calls) == 1


# --------------------------------------------------------------------------
# R12 : la matiere donnee aux noteurs
# --------------------------------------------------------------------------

MATERIAL_SIGNALS = "Signaux : 4 pics audio (max +12.5 dB), 6 changements de plan (x 2.5 la médiane de la vidéo), parole 0 %"
MATERIAL_FRAMES = "Images : 125.0 s : un tir (combat, intensité 4/10) ; 140.0 s : une explosion (mort, intensité 9/10)"


def speechless(video_dir):
    mute(video_dir, 20, 39)
    write_action(video_dir, passage(120.0, 150.0, frames=[frame(125.0, "un tir", "combat", 4),
                                                         frame(140.0, "une explosion", "mort", 9)]))


def test_the_comparison_call_gets_the_action_material(tmp_path, video_dir, rubric_path):
    speechless(video_dir)

    fake = go(tmp_path, rubric_path, [{"moments": []}, rate(GOOD)])

    compare = fake.calls[1]
    for line in ("Parole : (aucune)", MATERIAL_SIGNALS, MATERIAL_FRAMES):
        assert line in compare.prompt


def test_the_jury_gets_the_same_material(tmp_path, video_dir, rubric_path):
    speechless(video_dir)

    fake = go(
        tmp_path, rubric_path,
        with_jury({"moments": []}, judge_by_marker({"Parole : (aucune)": GOOD})),
        config=auto_config(tmp_path, rubric_path, candidates=PLUS),
    )

    jury_prompts = [c.prompt for c in fake.calls if c.usage.startswith("jury_")]
    assert jury_prompts
    for prompt in jury_prompts:
        for line in ("Parole : (aucune)", MATERIAL_SIGNALS, MATERIAL_FRAMES):
            assert line in prompt


def test_the_speech_of_an_action_candidate_is_quoted(tmp_path, video_dir, rubric_path):
    write_action(video_dir, passage(10.0, 45.0, speech_ratio=0.9, frames=[]))

    fake = go(tmp_path, rubric_path, [{"moments": []}, rate(GOOD)])

    prompt = fake.calls[1].prompt
    assert 'Parole : "mot2_0 mot2_1 mot2_2 mot2_3 mot2_4. mot3_0' in prompt
    assert "mot8_4." in prompt
    assert "Images : (aucune)" in prompt


def test_the_proposer_prompt_lists_the_action_passages(tmp_path, video_dir, rubric_path):
    speechless(video_dir)

    fake = go(tmp_path, rubric_path, [{"moments": []}, rate(GOOD)])

    prompt = fake.calls[0].prompt
    assert "Passages d'action" in prompt
    assert "[120.0-150.0] score 0.80 : combat, mort" in prompt


def test_the_text_of_a_transcript_candidate_is_unchanged(tmp_path, video_dir, rubric_path):
    speechless(video_dir)

    fake = go(
        tmp_path, rubric_path,
        with_jury({"moments": [moment(10.25, 44.65, GOOD)]}, judge_by_marker({"mot2_0": GOOD, "Parole": WEAK})),
        config=auto_config(tmp_path, rubric_path, candidates=PLUS),
    )

    prompt = next(c.prompt for c in fake.calls if c.usage.startswith("jury_"))
    assert "Texte : « mot2_0 mot2_1 mot2_2 mot2_3 mot2_4. mot3_0" in prompt


# --------------------------------------------------------------------------
# R13 : notation
# --------------------------------------------------------------------------


def test_with_the_jury_action_candidates_are_rated_with_the_others_and_no_call_is_added(
    tmp_path, video_dir, rubric_path
):
    speechless(video_dir)
    judges = judge_by_marker({"Parole : (aucune)": {**GOOD, "hook": 10}, "mot2_0": WEAK})

    fake = go(
        tmp_path, rubric_path,
        with_jury({"moments": [moment(10.25, 44.65, WEAK)]}, judges),
        config=auto_config(tmp_path, rubric_path, candidates=PLUS),
    )

    usages = [c.usage for c in fake.calls]
    assert usages.count("moments") == 1
    assert len(usages) == 6  # 1 proposeur + 5 juges, comme sans candidats d'action
    data = read_moments(video_dir)
    [m] = data["moments"]
    assert (m["source"], m["start"], m["scores"]["hook"]) == ("action", 120.0, 10)


def test_in_single_selection_one_extra_moments_call_rates_only_the_action_candidates(
    tmp_path, video_dir, rubric_path
):
    write_action(video_dir, passage(100.0, 130.0, id="a0"), passage(150.0, 180.0, id="a1"))

    fake = go(
        tmp_path, rubric_path,
        [{"moments": [moment(10.25, 44.65, GOOD)]},
         {"moments": [{"id": 0, "justification": "a", "scores": GOOD}, {"id": 1, "justification": "b", "scores": WEAK}]}],
    )

    assert [c.usage for c in fake.calls] == ["moments", "moments"]
    schema = fake.calls[1].schema
    assert (schema["properties"]["moments"]["minItems"], schema["properties"]["moments"]["maxItems"]) == (2, 2)
    assert "Candidats" in fake.calls[1].prompt and "mot0_0" not in fake.calls[1].prompt.split("## Candidats")[1]
    data = read_moments(video_dir)
    assert sorted((m["source"], m["start"]) for m in data["moments"]) == [("action", 100.25), ("transcript", 10.25)]
    [low] = [r for r in data["rejected"] if r["source"] == "action"]
    assert "min_score" in low["reason"]


def test_a_well_rated_action_candidate_evicts_an_overlapping_transcript_candidate(tmp_path, video_dir, rubric_path):
    write_action(video_dir, passage(30.0, 60.0))

    go(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65, GOOD)]}, rate({**GOOD, "hook": 10})])

    data = read_moments(video_dir)
    assert [(m["source"], m["start"], m["end"]) for m in data["moments"]] == [("action", 30.25, 59.65)]
    [r] = data["rejected"]
    assert (r["source"], r["start"]) == ("transcript", 10.25)
    assert r["reason"].startswith("chevauche un moment mieux note")


def test_a_better_rated_transcript_candidate_evicts_an_overlapping_action_candidate(tmp_path, video_dir, rubric_path):
    write_action(video_dir, passage(30.0, 60.0))

    go(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65, GOOD)]}, rate(BORDER)])

    data = read_moments(video_dir)
    assert [(m["source"], m["start"]) for m in data["moments"]] == [("transcript", 10.25)]
    [r] = data["rejected"]
    assert (r["source"], r["start"]) == ("action", 30.25)
    assert r["reason"].startswith("chevauche un moment mieux note")


def test_gate_and_min_score_apply_to_action_candidates(tmp_path, video_dir):
    p = _rubric_with_gate(tmp_path, GATE)
    write_action(video_dir, passage(100.0, 130.0, id="a0"), passage(300.0, 330.0, id="a1"))
    gated = {"hook": 9, "standalone": 9, "payoff": 9, "emotion": 3, "value": 5, "trend": 0}

    go(tmp_path, p, [{"moments": []},
                     {"moments": [{"id": 0, "justification": "a", "scores": gated},
                                  {"id": 1, "justification": "b", "scores": GOOD}]}])

    data = read_moments(video_dir)
    assert [m["start"] for m in data["moments"]] == [300.25]
    [r] = data["rejected"]
    assert r["reason"] == "emotion 3 < seuil éliminatoire 5 (grille)"
    assert r["source"] == "action"


# --------------------------------------------------------------------------
# R14 : moments.json et re-notation
# --------------------------------------------------------------------------


def test_every_moment_and_scored_rejection_carries_its_source_and_the_action_block(tmp_path, video_dir, rubric_path):
    speechless(video_dir)
    write_action(
        video_dir,
        passage(120.0, 150.0, id="a0", score=0.9,
                frames=[frame(125.0, "un tir", "combat", 4), frame(140.0, "une explosion", "mort", 9)]),
        passage(160.0, 190.0, id="a1", score=0.7),
    )

    go(tmp_path, rubric_path, [
        {"moments": [moment(10.25, 44.65, GOOD)]},
        {"moments": [{"id": 0, "justification": "a", "scores": GOOD}, {"id": 1, "justification": "b", "scores": WEAK}]},
    ])

    data = read_moments(video_dir)
    by_start = {m["start"]: m for m in data["moments"]}
    assert by_start[10.25]["source"] == "transcript" and "action" not in by_start[10.25]
    assert by_start[120.0]["action"] == {
        "id": "a0", "score": 0.9,
        "signals": {"audio_peaks": 4, "audio_peak_max_db": 12.5, "scene_cuts": 6, "scene_cuts_ratio": 2.5,
                    "speech_ratio": 0.0},
        "frames": [125.0, 140.0],
    }
    [low] = data["rejected"]
    assert (low["source"], low["action"]["id"], low["final_score"]) == ("action", "a1", 59.2)


def test_transcript_mode_is_byte_identical_whatever_the_action_file(tmp_path, video_dir, rubric_path):
    proposal = [{"moments": [moment(10.25, 44.65, GOOD), moment(100.25, 134.65, WEAK)]}]
    base = go(tmp_path, rubric_path, proposal, config=make_config(tmp_path, rubric_path))
    reference = (video_dir / "moments.json").read_bytes()
    (video_dir / "moments.json").unlink()
    write_action(video_dir, passage(300.0, 330.0))

    explicit = go(tmp_path, rubric_path, proposal, config=make_config(tmp_path, rubric_path, candidates="transcript"))

    assert (video_dir / "moments.json").read_bytes() == reference
    assert [c.prompt for c in explicit.calls] == [c.prompt for c in base.calls]
    assert "source" not in reference.decode() and "Passages d'action" not in explicit.calls[0].prompt


def test_rescore_after_vision_keeps_an_action_candidate_off_the_sentence_boundaries(tmp_path, video_dir, rubric_path):
    from clipper import moments as m

    write_action(video_dir, passage(12.0, 47.5))
    go(tmp_path, rubric_path, [{"moments": []}, rate(GOOD)], action_snap_seconds=1.0)
    before = read_moments(video_dir)["moments"][0]
    assert before["bonus"]["visual"] == 0
    (video_dir / "vision.json").write_text(
        json.dumps({"frames": [{"timecode": 20.0, "description": "boum", "striking": True}]}), encoding="utf-8"
    )

    m._rescore(video_dir, video_dir / "moments.json",
               {**m.CONFIG_DEFAULTS, "rubric_path": str(rubric_path), "candidates": PLUS})

    data = read_moments(video_dir)
    [after] = data["moments"]
    assert (after["start"], after["end"], after["source"]) == (12.0, 47.5, "action")
    assert after["action"] == before["action"]
    assert after["bonus"]["visual"] == 2
    assert after["final_score"] > before["final_score"]


def test_rescore_reapplies_the_gate_to_an_action_candidate(tmp_path, video_dir):
    from clipper import moments as m

    p = _rubric_with_gate(tmp_path, '[gate]\ncriterion = "emotion"\nmin = 5\n')
    write_action(video_dir, passage(12.0, 47.5))
    go(tmp_path, p, [{"moments": []}, rate(GOOD)], action_snap_seconds=1.0)
    assert len(read_moments(video_dir)["moments"]) == 1
    p.write_text(TEST_RUBRIC + '\n[gate]\ncriterion = "emotion"\nmin = 7\n', encoding="utf-8")
    (video_dir / "vision.json").write_text(json.dumps({"frames": []}), encoding="utf-8")

    m._rescore(video_dir, video_dir / "moments.json", {**m.CONFIG_DEFAULTS, "rubric_path": str(p)})

    data = read_moments(video_dir)
    assert data["moments"] == []
    [r] = data["rejected"]
    assert r["reason"] == "emotion 6 < seuil éliminatoire 7 (grille)"
    assert (r["source"], r["start"], r["end"]) == ("action", 12.0, 47.5)
