from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import pytest

from clipper import llm
from clipper.config import Config
from clipper.llm.fake import FakeBackend

REPO = Path(__file__).resolve().parents[1]
VIDEO_ID = "abcdefghijk"

# Grille de test figee : les tests de calcul ne dependent pas des reglages
# que l'utilisateur peut changer dans le rubric.toml du depot.
TEST_RUBRIC = """
min_score = 60
trend_keywords = ["GTA 6", "Vice City"]

[criteria.hook]
weight = 3
question = "La 1re phrase arrete-t-elle le scroll ?"
[criteria.standalone]
weight = 3
question = "Comprehensible seul ?"
[criteria.payoff]
weight = 2
question = "Arc complet ?"
[criteria.emotion]
weight = 2
question = "Reaction forte ?"
[criteria.value]
weight = 2
question = "Info, leak, avis ?"
[criteria.trend]
weight = 1
question = "Mots-cles tendance ?"

[durations]
single_min = 20
single_max = 45
part_min = 60
part_max = 90
min_parts = 2
tolerance = 3

[bonus]
max_total = 6
replayed = 5
audio_peaks = 3
audio_peaks_full = 2
visual = 2

[exclusions]
sponsorblock_categories = ["sponsor", "intro", "outro", "selfpromo"]
"""

# Notes -> (9*3 + 8*3 + 7*2 + 6*2 + 5*2 + 0*1) / 13 * 10 = 66.9
GOOD = {"hook": 9, "standalone": 8, "payoff": 7, "emotion": 6, "value": 5, "trend": 0}
# (7*3 + 7*3 + 6*2 + 6*2 + 5*2 + 1*1) / 13 * 10 = 59.2
WEAK = {"hook": 7, "standalone": 7, "payoff": 6, "emotion": 6, "value": 5, "trend": 1}
# (7*3 + 7*3 + 6*2 + 6*2 + 5*2 + 2*1) / 13 * 10 = 60.0
BORDER = {"hook": 7, "standalone": 7, "payoff": 6, "emotion": 6, "value": 5, "trend": 2}


# --------------------------------------------------------------------------
# Fixtures : une video de 100 phrases de 5 mots ; la phrase k va de
# 5k + 0.25 s a 5k + 4.65 s (dernier mot), 0.6 s de pause entre deux.
# --------------------------------------------------------------------------


def sentence_start(k):
    return 5 * k + 0.25


def sentence_end(k):
    return 5 * k + 4.65


def make_transcript(n=100):
    segments = []
    for k in range(n):
        words = []
        for i in range(5):
            start = sentence_start(k) + i * 0.9
            text = f" mot{k}_{i}" + ("." if i == 4 else "")
            words.append({"word": text, "start": start, "end": start + 0.8, "probability": 0.9})
        segments.append(
            {
                "id": k,
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": "".join(w["word"] for w in words),
                "words": words,
            }
        )
    return {"video_id": VIDEO_ID, "language": "fr", "duration": 500.0, "segments": segments}


META = {
    "video_id": VIDEO_ID,
    "title": "GTA 6 : on decortique le trailer",
    "description": "Live du soir",
    "duration": 500.0,
    "channel": "ChaineTest",
    "chapters": [
        {"start_time": 0.0, "end_time": 250.0, "title": "Intro et news"},
        {"start_time": 250.0, "end_time": 500.0, "title": "Analyse du trailer Vice City"},
    ],
    "heatmap": [
        {"start_time": 0.0, "end_time": 250.0, "value": 0.0},
        {"start_time": 250.0, "end_time": 500.0, "value": 0.87},
    ],
    "sponsorblock_segments": [
        {"start_time": 200.0, "end_time": 240.0, "category": "sponsor", "title": "Sponsor", "type": "skip"},
        {"start_time": 400.0, "end_time": 420.0, "category": "interaction", "title": "Interaction", "type": "skip"},
    ],
}

AUDIO = {"window_seconds": 1.0, "energy_db": [], "peaks": [{"timecode": 333.0, "relative_db": 9.5}]}


@pytest.fixture
def video_dir(tmp_path):
    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(META), encoding="utf-8")
    (d / "transcript.json").write_text(json.dumps(make_transcript()), encoding="utf-8")
    (d / "audio.json").write_text(json.dumps(AUDIO), encoding="utf-8")
    return d


@pytest.fixture
def rubric_path(tmp_path):
    p = tmp_path / "rubric.toml"
    p.write_text(TEST_RUBRIC, encoding="utf-8")
    return p


def make_config(tmp_path, rubric_path, mode="review", **moments):
    return Config(
        mode=mode,
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={"moments": {"rubric_path": str(rubric_path), **moments}},
    )


def moment(start, end, scores=GOOD, fmt="single", breaks=(), hook="accroche", why="ca marche"):
    return {
        "start": start,
        "end": end,
        "hook_text": hook,
        "justification": why,
        "format": fmt,
        "part_breaks": list(breaks),
        "scores": dict(scores),
    }


def run(tmp_path, rubric_path, responses, examples=None, config=None, **kwargs):
    from clipper.moments import run as run_moments

    fake = FakeBackend(responses)
    config = config or make_config(tmp_path, rubric_path)
    with llm.use_backend(fake):
        path = run_moments(VIDEO_ID, tmp_path / "workspace", config=config, examples=examples, **kwargs)
    return fake, path


def read_moments(video_dir):
    return json.loads((video_dir / "moments.json").read_text(encoding="utf-8"))


def spans(data):
    return [(m["start"], m["end"]) for m in data["moments"]]


# --------------------------------------------------------------------------
# rubric.toml du depot : conforme a SPEC-53f3
# --------------------------------------------------------------------------


def test_repo_rubric_matches_the_spec():
    from clipper.moments import load_rubric

    rubric = load_rubric(REPO / "rubric.toml")
    assert {name: c["weight"] for name, c in rubric["criteria"].items()} == {
        "hook": 3, "standalone": 3, "payoff": 2, "emotion": 2, "value": 2, "trend": 1,
    }
    assert all(c["question"].strip() for c in rubric["criteria"].values())
    assert rubric["min_score"] == 60
    d = rubric["durations"]
    assert (d["single_min"], d["single_max"], d["part_min"], d["part_max"], d["min_parts"]) == (20, 45, 60, 90, 2)
    for keyword in ("GTA 6", "trailer", "date de sortie", "Vice City", "Lucia"):
        assert keyword in rubric["trend_keywords"]
    assert set(rubric["exclusions"]["sponsorblock_categories"]) == {"sponsor", "intro", "outro", "selfpromo"}
    assert {"max_total", "replayed", "audio_peaks", "visual"} <= set(rubric["bonus"])


def test_rubric_missing_a_weight_is_refused(tmp_path):
    from clipper.moments import MomentsError, load_rubric

    p = tmp_path / "rubric.toml"
    p.write_text(TEST_RUBRIC.replace("weight = 1\n", ""), encoding="utf-8")
    with pytest.raises(MomentsError, match="trend"):
        load_rubric(p)


# --------------------------------------------------------------------------
# Ce qui part a clipper.llm (usage moments)
# --------------------------------------------------------------------------


def test_prompt_carries_transcript_and_every_signal(tmp_path, video_dir, rubric_path):
    (video_dir / "vision.json").write_text(
        json.dumps({"frames": [{"timecode": 312.0, "description": "Lucia braque une banque", "striking": True}]}),
        encoding="utf-8",
    )
    examples = [
        {"video_id": "x", "moment": {"start": 1, "end": 30}, "decision": "accepted",
         "texte_moment": "La date de sortie a fuite", "commentaire": "top"},
        {"video_id": "x", "moment": {"start": 50, "end": 80}, "decision": "rejected",
         "texte_moment": "Bon on regarde le chat", "commentaire": "trop mou"},
    ]
    fake, _ = run(tmp_path, rubric_path, [{"moments": []}], examples=examples)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.usage == "moments"
    prompt = call.prompt
    # transcription complete horodatee : premiere et derniere phrase, avec leurs timecodes
    assert "[0.2-4.7] mot0_0 mot0_1 mot0_2 mot0_3 mot0_4." in prompt
    assert "[495.2-499.7] mot99_0" in prompt
    assert all(f"mot{k}_0" in prompt for k in range(100))
    # chapitres, heatmap, pics audio, SponsorBlock, vision, feedback
    assert "Analyse du trailer Vice City" in prompt
    assert "0.87" in prompt
    assert "333.0" in prompt
    assert "sponsor" in prompt and "200.0" in prompt and "240.0" in prompt
    assert "Lucia braque une banque" in prompt
    assert "La date de sortie a fuite" in prompt and "trop mou" in prompt
    # grille et mots-cles tendance
    assert "La 1re phrase arrete-t-elle le scroll ?" in prompt
    assert "Vice City" in prompt
    # schema de reponse : notes par critere, pas de score final demande au LLM
    item = call.schema["properties"]["moments"]["items"]
    assert set(item["properties"]["scores"]["required"]) == {
        "hook", "standalone", "payoff", "emotion", "value", "trend",
    }
    assert "final_score" not in item["properties"]
    assert call.images == []


def test_no_vision_file_is_fine(tmp_path, video_dir, rubric_path):
    fake, _ = run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65)]}])
    assert len(read_moments(video_dir)["moments"]) == 1


# --------------------------------------------------------------------------
# moments.json conforme a la spec (regle 5)
# --------------------------------------------------------------------------


def test_writes_moments_json_with_spec_fields(tmp_path, video_dir, rubric_path):
    _, path = run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65, why="Revelation sur la date")]}])

    assert Path(path) == video_dir / "moments.json"
    data = read_moments(video_dir)
    assert data["video_id"] == VIDEO_ID
    [m] = data["moments"]
    assert (m["start"], m["end"]) == (10.2, 44.7)
    assert m["scores"] == GOOD
    assert m["final_score"] == 66.9
    assert m["justification"] == "Revelation sur la date"
    assert m["hook_text"] == "mot2_0 mot2_1 mot2_2 mot2_3 mot2_4."
    assert m["format"] == "single"
    assert m["parts"] == []


def test_multipart_story_lists_its_parts_on_sentence_ends(tmp_path, video_dir, rubric_path):
    # phrases 50..77 : 250.25 -> 389.65 (139.4 s), coupure demandee vers 320 s
    run(tmp_path, rubric_path, [{"moments": [moment(250.25, 389.65, fmt="multipart", breaks=[320.3])]}])

    [m] = read_moments(video_dir)["moments"]
    assert m["format"] == "multipart"
    assert [(p["start"], p["end"]) for p in m["parts"]] == [(250.2, 319.7), (320.2, 389.7)]


# --------------------------------------------------------------------------
# Score final calcule en Python
# --------------------------------------------------------------------------


def test_final_score_is_weighted_mean_of_criterion_notes(tmp_path, video_dir, rubric_path):
    run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65, scores=GOOD), moment(100.25, 134.65, scores=BORDER)]}])

    scores = sorted(m["final_score"] for m in read_moments(video_dir)["moments"])
    assert scores == [60.0, 66.9]


def test_measured_signals_add_a_capped_bonus(tmp_path, video_dir, rubric_path):
    # 300.25 -> 334.65 : heatmap 0.87 partout (4.35), 1 pic audio sur 2 (1.5),
    # une image marquante (2) -> 7.85, plafonne a 6
    (video_dir / "vision.json").write_text(
        json.dumps({"frames": [{"timecode": 312.0, "description": "explosion", "striking": True}]}),
        encoding="utf-8",
    )
    run(tmp_path, rubric_path, [{"moments": [moment(300.25, 334.65, scores=GOOD)]}])

    [m] = read_moments(video_dir)["moments"]
    assert m["final_score"] == 72.9
    assert m["bonus"] == {"replayed": 4.35, "audio_peaks": 1.5, "visual": 2.0, "total": 6.0}


# --------------------------------------------------------------------------
# Regles de la spec
# --------------------------------------------------------------------------


def test_sponsorblock_segments_are_excluded(tmp_path, video_dir, rubric_path):
    run(
        tmp_path,
        rubric_path,
        [{"moments": [
            moment(190.25, 224.65),  # chevauche le sponsor 200-240
            moment(395.25, 429.65),  # chevauche une "interaction" : categorie non exclue
            moment(10.25, 44.65),
        ]}],
    )

    data = read_moments(video_dir)
    assert sorted(spans(data)) == [(10.2, 44.7), (395.2, 429.7)]
    assert any("sponsor" in r["reason"] for r in data["rejected"])


def test_bounds_are_snapped_to_sentence_boundaries(tmp_path, video_dir, rubric_path):
    # 11.7 est dans la phrase 2 (10.25-14.65) : debut le plus proche 10.25 ;
    # 43.1 est dans la phrase 8 (40.25-44.65) : fin la plus proche 44.65
    run(tmp_path, rubric_path, [{"moments": [moment(11.7, 43.1)]}])

    assert spans(read_moments(video_dir)) == [(10.2, 44.7)]


def test_sentence_boundaries_come_from_punctuation_inside_a_segment(tmp_path, video_dir, rubric_path):
    transcript = make_transcript()
    # la phrase 2 se coupe en deux apres son 3e mot : une phrase repart a 12.95
    seg = transcript["segments"][2]
    seg["words"][2]["word"] = " mot2_2?"
    (video_dir / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")

    run(tmp_path, rubric_path, [{"moments": [moment(12.2, 44.65)]}])

    [m] = read_moments(video_dir)["moments"]
    assert m["start"] == 12.9
    assert m["hook_text"] == "mot2_3 mot2_4."


def test_overlapping_moments_keep_the_best_scored(tmp_path, video_dir, rubric_path):
    better = {**GOOD, "hook": 10}
    run(
        tmp_path,
        rubric_path,
        [{"moments": [
            moment(10.25, 44.65, scores=GOOD),
            moment(30.25, 64.65, scores=better),   # recouvre le premier, mieux note
            moment(60.25, 94.65, scores=GOOD),     # recouvre le deuxieme
            moment(150.25, 184.65, scores=GOOD),   # isole
        ]}],
    )

    data = read_moments(video_dir)
    assert sorted(spans(data)) == [(30.2, 64.7), (150.2, 184.7)]
    assert sum("chevauche" in r["reason"] for r in data["rejected"]) == 2


def test_moments_under_min_score_are_dropped(tmp_path, video_dir, rubric_path):
    run(
        tmp_path,
        rubric_path,
        [{"moments": [moment(10.25, 44.65, scores=WEAK), moment(100.25, 134.65, scores=BORDER)]}],
    )

    data = read_moments(video_dir)
    assert spans(data) == [(100.2, 134.7)]
    [rejected] = data["rejected"]
    assert rejected["final_score"] == 59.2 and "min_score" in rejected["reason"]


def test_all_moments_above_min_score_are_kept_without_cap(tmp_path, video_dir, rubric_path):
    # i = 5 tomberait dans le sponsor 200-240
    many = [moment(sentence_start(8 * i), sentence_end(8 * i + 6)) for i in range(12) if i != 5]
    run(tmp_path, rubric_path, [{"moments": many}])
    assert len(read_moments(video_dir)["moments"]) == 11


def test_duration_outside_the_rubric_bounds_is_rejected(tmp_path, video_dir, rubric_path):
    run(
        tmp_path,
        rubric_path,
        [{"moments": [
            moment(10.25, 19.65),                       # single de 9.4 s
            moment(100.25, 174.65),                     # single de 74.4 s
            moment(250.25, 309.65, fmt="multipart"),    # multipart de 59.4 s
            moment(400.25, 434.65),
        ]}],
    )

    data = read_moments(video_dir)
    assert spans(data) == [(400.2, 434.7)]
    assert sum("duree" in r["reason"] for r in data["rejected"]) == 3


# --------------------------------------------------------------------------
# Echecs et cache
# --------------------------------------------------------------------------


def test_invalid_llm_answer_fails_and_writes_nothing(tmp_path, video_dir, rubric_path):
    with pytest.raises(llm.SchemaError):
        run(tmp_path, rubric_path, [{"moments": [{"start": 10.0}]}])
    assert not (video_dir / "moments.json").exists()


def test_missing_input_is_an_error(tmp_path, video_dir, rubric_path):
    from clipper.moments import MomentsError

    (video_dir / "audio.json").unlink()
    with pytest.raises(MomentsError, match="audio.json"):
        run(tmp_path, rubric_path, [])


def test_existing_result_is_not_recomputed_unless_forced(tmp_path, video_dir, rubric_path):
    run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65)]}])
    fake, _ = run(tmp_path, rubric_path, [])
    assert fake.calls == []

    fake, _ = run(tmp_path, rubric_path, [{"moments": []}], force=True)
    assert len(fake.calls) == 1
    assert read_moments(video_dir)["moments"] == []


# --------------------------------------------------------------------------
# Re-notation apres vision (TASK-e493) : moments.json present et vision.json
# plus recent -> bonus visuel, score final, min_score et chevauchement
# recalcules sur les candidats enregistres, sans aucun appel LLM.
# --------------------------------------------------------------------------


def _llm_forbidden(request):
    raise AssertionError(f"appel LLM {request.usage!r} pendant la re-notation")


def write_vision_after_moments(video_dir, frames):
    path = video_dir / "vision.json"
    path.write_text(json.dumps({"frames": frames}), encoding="utf-8")
    later = (video_dir / "moments.json").stat().st_mtime_ns + 5_000_000_000
    os.utime(path, ns=(later, later))


def rescore(tmp_path, rubric_path, **kwargs):
    """Relance l'etape avec un FakeBackend qui echoue s'il est appele."""
    return run(tmp_path, rubric_path, [_llm_forbidden] * 5, **kwargs)


def striking(timecode):
    return {"timecode": timecode, "description": "explosion", "striking": True}


def scored(data):
    """Candidats notes (retenus, et rejetes pour score ou chevauchement), par debut."""
    notes = data["moments"] + [r for r in data["rejected"] if "final_score" in r]
    return sorted(notes, key=lambda m: m["start"])


def test_rescore_after_vision_makes_no_llm_call(tmp_path, video_dir, rubric_path):
    run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65, scores=WEAK), moment(100.25, 134.65)]}])
    write_vision_after_moments(video_dir, [striking(20.0)])

    fake, path = rescore(tmp_path, rubric_path)

    assert fake.calls == []
    assert path == video_dir / "moments.json"
    assert "rescored" in read_moments(video_dir)


def test_rescore_keeps_criterion_notes_bounds_and_justifications(tmp_path, video_dir, rubric_path):
    run(
        tmp_path,
        rubric_path,
        [{"moments": [
            moment(10.25, 44.65, scores=WEAK, hook="faible", why="un peu mou"),
            moment(100.25, 134.65, why="tres bon"),
            moment(250.25, 369.65, fmt="multipart", breaks=[309.65], why="arc complet"),
        ]}],
    )
    before = scored(read_moments(video_dir))
    write_vision_after_moments(video_dir, [striking(20.0), striking(110.0), striking(300.0)])

    rescore(tmp_path, rubric_path)

    after = scored(read_moments(video_dir))
    keys = ("start", "end", "duration", "format", "parts", "scores", "justification", "hook_text")
    assert len(after) == 3
    assert [{k: m[k] for k in keys} for m in after] == [{k: m[k] for k in keys} for m in before]


def test_rescore_adds_the_visual_bonus_and_recomputes_the_final_score(tmp_path, video_dir, rubric_path):
    # 100.25 -> 134.65, aucun signal : 66.9 ; image marquante : +2 -> 68.9
    run(tmp_path, rubric_path, [{"moments": [moment(100.25, 134.65)]}])
    write_vision_after_moments(video_dir, [striking(110.0)])

    rescore(tmp_path, rubric_path)

    [m] = read_moments(video_dir)["moments"]
    assert m["bonus"] == {"replayed": 0.0, "audio_peaks": 0.0, "visual": 2.0, "total": 2.0}
    assert m["final_score"] == 68.9


def test_rescore_keeps_the_measured_bonus_and_caps_the_total(tmp_path, video_dir, rubric_path):
    # 300.25 -> 334.65 : heatmap 4.35 + audio 1.5 = 5.85 -> 66.9 + 5.85 = 72.8 ;
    # + image marquante 2 -> 7.85, plafonne a 6 -> 72.9
    run(tmp_path, rubric_path, [{"moments": [moment(300.25, 334.65)]}])
    assert read_moments(video_dir)["moments"][0]["final_score"] == 72.8
    write_vision_after_moments(video_dir, [striking(312.0)])

    rescore(tmp_path, rubric_path)

    [m] = read_moments(video_dir)["moments"]
    assert m["bonus"] == {"replayed": 4.35, "audio_peaks": 1.5, "visual": 2.0, "total": 6.0}
    assert m["final_score"] == 72.9


def test_rescore_promotes_a_moment_rejected_for_score_and_says_what_changed(tmp_path, video_dir, rubric_path):
    # WEAK = 59.2 < 60 ; avec l'image marquante : 61.2, retenu.
    run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65, scores=WEAK), moment(100.25, 134.65)]}])
    assert spans(read_moments(video_dir)) == [(100.2, 134.7)]
    write_vision_after_moments(video_dir, [striking(20.0)])

    rescore(tmp_path, rubric_path)

    data = read_moments(video_dir)
    assert sorted(spans(data)) == [(10.2, 44.7), (100.2, 134.7)]
    assert not [r for r in data["rejected"] if "min_score" in r["reason"]]
    promoted = next(m for m in data["moments"] if m["start"] == 10.2)
    assert promoted["final_score"] == 61.2
    assert data["rescored"]["changed"] == [{
        "id": promoted["id"],
        "start": 10.2,
        "end": 44.7,
        "hook_text": promoted["hook_text"],
        "before": {"final_score": 59.2, "retained": False},
        "after": {"final_score": 61.2, "retained": True},
    }]


def test_rescore_without_striking_frame_in_a_moment_changes_nothing(tmp_path, video_dir, rubric_path):
    run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65, scores=WEAK), moment(100.25, 134.65)]}])
    first = read_moments(video_dir)
    write_vision_after_moments(video_dir, [striking(80.0), {"timecode": 20.0, "description": "decor", "striking": False}])

    rescore(tmp_path, rubric_path)

    data = read_moments(video_dir)
    assert data["rescored"]["changed"] == []
    assert data["moments"] == first["moments"]
    assert data["rejected"] == first["rejected"]


def test_rescore_recomputes_the_overlap_between_candidates(tmp_path, video_dir, rubric_path):
    # meme note : le premier garde la place, le second est rejete pour
    # chevauchement ; une image marquante dans le second seul le fait passer
    # devant (68.9 contre 66.9).
    run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65), moment(30.25, 64.65)]}])
    assert spans(read_moments(video_dir)) == [(10.2, 44.7)]
    write_vision_after_moments(video_dir, [striking(60.0)])

    rescore(tmp_path, rubric_path)

    data = read_moments(video_dir)
    assert spans(data) == [(30.2, 64.7)]
    [overlap] = [r for r in data["rejected"] if "chevauche" in r["reason"]]
    assert (overlap["start"], overlap["final_score"]) == (10.2, 66.9)
    assert {(c["start"], c["before"]["retained"], c["after"]["retained"]) for c in data["rescored"]["changed"]} == {
        (10.2, True, False), (30.2, False, True),
    }


def test_rescore_leaves_rubric_rejections_untouched(tmp_path, video_dir, rubric_path):
    run(
        tmp_path,
        rubric_path,
        [{"moments": [
            moment(190.25, 224.65),     # sponsor
            moment(10.25, 19.65),       # trop court
            moment(100.25, 134.65),
        ]}],
    )
    first = [r for r in read_moments(video_dir)["rejected"] if "final_score" not in r]
    assert len(first) == 2
    write_vision_after_moments(video_dir, [striking(15.0), striking(200.0)])

    rescore(tmp_path, rubric_path)

    assert [r for r in read_moments(video_dir)["rejected"] if "final_score" not in r] == first


def test_rescore_uses_exact_bounds_so_adjacent_moments_do_not_overlap(tmp_path, video_dir, rubric_path):
    # phrases presque collees (0.02 s d'ecart) : la fin d'un moment arrondie
    # au dixieme superieur depasse le debut du suivant arrondi au dixieme
    # inferieur ; seules les bornes exactes disent qu'ils ne se chevauchent pas.
    transcript = make_transcript()
    for k, seg in enumerate(transcript["segments"]):
        for w in seg["words"]:
            w["start"] -= 0.58 * k
            w["end"] -= 0.58 * k
        seg["start"], seg["end"] = seg["words"][0]["start"], seg["words"][-1]["end"]
    (video_dir / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
    segs = transcript["segments"]
    run(tmp_path, rubric_path, [{"moments": [
        moment(segs[2]["start"], segs[8]["end"]), moment(segs[9]["start"], segs[15]["end"]),
    ]}])
    (a_start, a_end), (b_start, b_end) = sorted(spans(read_moments(video_dir)))
    assert a_end > b_start, "le cas teste suppose des bornes publiques qui se recouvrent"
    write_vision_after_moments(video_dir, [striking(segs[3]["start"])])

    rescore(tmp_path, rubric_path)

    assert sorted(spans(read_moments(video_dir))) == [(a_start, a_end), (b_start, b_end)]


def test_rescore_refuses_bounds_that_are_not_sentence_boundaries(tmp_path, video_dir, rubric_path):
    from clipper.moments import MomentsError

    run(tmp_path, rubric_path, [{"moments": [moment(100.25, 134.65)]}])
    data = read_moments(video_dir)
    data["moments"][0]["start"] = 102.0
    (video_dir / "moments.json").write_text(json.dumps(data), encoding="utf-8")
    write_vision_after_moments(video_dir, [striking(110.0)])

    with pytest.raises(MomentsError, match="102.0"):
        rescore(tmp_path, rubric_path)


def test_older_vision_file_does_not_trigger_a_rescore(tmp_path, video_dir, rubric_path):
    (video_dir / "vision.json").write_text(json.dumps({"frames": [striking(110.0)]}), encoding="utf-8")
    run(tmp_path, rubric_path, [{"moments": [moment(100.25, 134.65)]}])
    before = (video_dir / "moments.json").read_bytes()

    fake, _ = rescore(tmp_path, rubric_path)

    assert fake.calls == []
    assert (video_dir / "moments.json").read_bytes() == before


def test_forced_run_after_vision_asks_the_llm_again(tmp_path, video_dir, rubric_path):
    run(tmp_path, rubric_path, [{"moments": [moment(100.25, 134.65)]}])
    write_vision_after_moments(video_dir, [striking(110.0)])

    fake, _ = run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65)]}], force=True)

    assert [c.usage for c in fake.calls] == ["moments"]
    data = read_moments(video_dir)
    assert spans(data) == [(10.2, 44.7)]
    assert "rescored" not in data


# --------------------------------------------------------------------------
# Transcription trop longue : tranches avec recouvrement puis comparaison
# --------------------------------------------------------------------------


def test_long_transcript_goes_in_overlapping_chunks_then_a_comparison_round(tmp_path, video_dir, rubric_path):
    config = make_config(tmp_path, rubric_path, max_transcript_chars=2000, chunk_chars=2000, chunk_overlap_seconds=30)

    def dispatch(request):
        if "Candidats" in request.prompt:
            # tour final : re-note tout ; le premier remonte au-dessus de min_score
            assert "id 0" in request.prompt and "id 1" in request.prompt
            return {"moments": [
                {"id": 0, "justification": "revu", "scores": GOOD},
                {"id": 1, "justification": "revu", "scores": WEAK},
            ]}
        # chaque tranche propose un moment dans sa propre portion
        if "[10.2-14.7]" in request.prompt:
            return {"moments": [moment(10.25, 44.65, scores=WEAK)]}
        if "[450.2-454.7]" in request.prompt:
            return {"moments": [moment(450.25, 484.65, scores=GOOD)]}
        return {"moments": []}

    from clipper.moments import run as run_moments

    fake = FakeBackend([dispatch] * 30)
    with llm.use_backend(fake):
        run_moments(VIDEO_ID, tmp_path / "workspace", config=config)

    chunk_calls = [c for c in fake.calls if "Candidats" not in c.prompt]
    final_calls = [c for c in fake.calls if "Candidats" in c.prompt]
    assert len(chunk_calls) >= 2
    assert len(final_calls) == 1
    # chaque phrase apparait dans au moins une tranche, et des tranches se recouvrent
    seen = [sum(f"mot{k}_0 " in c.prompt for c in chunk_calls) for k in range(100)]
    assert min(seen) >= 1 and max(seen) >= 2

    # les notes retenues sont celles du tour final, pas celles des tranches
    data = read_moments(video_dir)
    by_start = sorted(data["moments"], key=lambda m: m["start"])
    assert [(m["start"], m["scores"]) for m in by_start] == [(10.2, GOOD), (450.2, WEAK)]
    assert by_start[0]["final_score"] == 66.9
    assert data["chunked"] is True


def test_comparison_round_must_rescore_every_candidate(tmp_path, video_dir, rubric_path):
    from clipper.moments import run as run_moments

    config = make_config(tmp_path, rubric_path, max_transcript_chars=2000, chunk_chars=2000, chunk_overlap_seconds=30)

    def dispatch(request):
        if "Candidats" in request.prompt:
            # deux notes, mais l'id 1 manque (l'id 0 est en double)
            return {"moments": [
                {"id": 0, "justification": "x", "scores": GOOD},
                {"id": 0, "justification": "y", "scores": GOOD},
            ]}
        if "[10.2-14.7]" in request.prompt:
            return {"moments": [moment(10.25, 44.65)]}
        if "[450.2-454.7]" in request.prompt:
            return {"moments": [moment(450.25, 484.65)]}
        return {"moments": []}

    fake = FakeBackend([dispatch] * 30)
    with llm.use_backend(fake), pytest.raises(llm.SchemaError, match=r"manquants \[1\]"):
        run_moments(VIDEO_ID, tmp_path / "workspace", config=config)
    assert not (video_dir / "moments.json").exists()


# --------------------------------------------------------------------------
# Selection par le jury (TASK-8e2f, ADR-ff87) : en mode auto ou avec
# [moments] selection = "jury", le proposeur donne les candidats, le jury
# (clipper.jury, 5 juges par defaut) les note ; ses notes agregees remplacent
# celles du proposeur.
# --------------------------------------------------------------------------

JUDGES = {"retention", "spectateur", "monteur", "avocat", "conformite"}
# Candidat vu par un juge : "### C3\nContexte : ...\nTexte : « motK_0 ..." ;
# K, la premiere phrase du candidat, dit de quel moment il s'agit.
_JURY_BLOCK = re.compile(r"### (C\d+)\n(?:Contexte : [^\n]*\n)?Texte : « mot(\d+)_0 ")


def jury_notes(notes, vetoes=None, debate=None):
    """Reponse factice d'un juge. ``notes[k]`` : notes du candidat qui
    commence a la phrase k, soit une grille (tous les juges), soit
    {juge: grille} ; ``vetoes[k]`` : raison du veto de conformite ;
    ``debate[k]`` : {juge: grille} renvoye au tour 2."""
    vetoes, debate = vetoes or {}, debate or {}

    def answer(request):
        judge = request.usage.removeprefix("jury_")
        second_round = "## Debat" in request.prompt
        refs = {ref: int(k) for ref, k in _JURY_BLOCK.findall(request.prompt)}
        item = request.schema["properties"]["candidates"]["items"]["properties"]
        out = []
        for ref in item["ref"]["enum"]:
            k = refs[ref]
            grid = notes[k] if "hook" in notes[k] else notes[k][judge]
            if second_round and judge in debate.get(k, {}):
                grid = debate[k][judge]
            entry = {"ref": ref, "argument": f"{judge} sur {ref}", "scores": dict(grid)}
            if "veto" in item:
                entry["veto"] = k in vetoes
                entry["veto_reason"] = vetoes.get(k, "")
            out.append(entry)
        return {"candidates": out}

    return answer


def with_jury(proposal, judges):
    """Un seul script pour le proposeur (usage moments) et les juges."""

    def dispatch(request):
        if request.usage == "moments":
            return proposal(request) if callable(proposal) else proposal
        return judges(request)

    return [dispatch]


def auto_config(tmp_path, rubric_path, **moments):
    return make_config(tmp_path, rubric_path, mode="auto", **moments)


def test_auto_mode_has_the_jury_rate_the_proposed_candidates(tmp_path, video_dir, rubric_path):
    proposal = {"moments": [moment(10.25, 44.65, scores=WEAK), moment(100.25, 134.65, scores=GOOD)]}
    fake, _ = run(
        tmp_path, rubric_path, with_jury(proposal, jury_notes({2: GOOD, 20: WEAK})),
        config=auto_config(tmp_path, rubric_path),
    )

    assert fake.calls[0].usage == "moments"
    jury_calls = fake.calls[1:]
    assert {c.usage for c in jury_calls} == {f"jury_{j}" for j in JUDGES}
    assert len(jury_calls) == 5  # tous d'accord : pas de debat
    assert all("mot2_0" in c.prompt and "mot20_0" in c.prompt for c in jury_calls)
    assert all("La 1re phrase arrete-t-elle le scroll ?" in c.prompt for c in jury_calls)
    data = read_moments(video_dir)
    assert data["selection"] == "jury"
    [m] = data["moments"]
    assert (m["start"], m["scores"], m["final_score"]) == (10.2, GOOD, 66.9)
    [low] = [r for r in data["rejected"] if "min_score" in r["reason"]]
    assert (low["start"], low["final_score"]) == (100.2, 59.2)


def test_jury_median_replaces_the_proposer_notes(tmp_path, video_dir, rubric_path):
    # proposeur : GOOD (66.9) ; jury : mediane par critere de GOOD, GOOD,
    # WEAK, WEAK, BORDER = WEAK (59.2) -> sous min_score.
    split = {"retention": GOOD, "spectateur": GOOD, "monteur": WEAK, "avocat": WEAK, "conformite": BORDER}
    run(
        tmp_path, rubric_path, with_jury({"moments": [moment(10.25, 44.65, scores=GOOD)]}, jury_notes({2: split})),
        config=auto_config(tmp_path, rubric_path),
    )

    data = read_moments(video_dir)
    assert data["moments"] == []
    [r] = data["rejected"]
    assert (r["scores"], r["final_score"]) == (WEAK, 59.2)
    assert r["jury"]["proposer"]["scores"] == GOOD


def test_jury_notes_keep_bonus_min_score_and_overlap_rules(tmp_path, video_dir, rubric_path):
    better = {**GOOD, "hook": 10}
    proposal = {"moments": [
        moment(300.25, 334.65, scores=GOOD),   # bonus mesure 5.85
        moment(10.25, 44.65, scores=better),
        moment(30.25, 64.65, scores=GOOD),     # recouvre le precedent
    ]}
    # jury : WEAK (59.2) + 5.85 = 65.1, retenu grace au bonus ; le
    # chevauchement se decide sur les notes du jury (inversees).
    run(
        tmp_path, rubric_path, with_jury(proposal, jury_notes({60: WEAK, 2: GOOD, 6: better})),
        config=auto_config(tmp_path, rubric_path),
    )

    data = read_moments(video_dir)
    assert sorted(spans(data)) == [(30.2, 64.7), (300.2, 334.7)]
    bonus = next(m for m in data["moments"] if m["start"] == 300.2)
    assert bonus["bonus"] == {"replayed": 4.35, "audio_peaks": 1.5, "visual": 0.0, "total": 5.85}
    assert bonus["final_score"] == 65.1
    [overlap] = [r for r in data["rejected"] if "chevauche" in r["reason"]]
    assert (overlap["start"], overlap["final_score"]) == (10.2, 66.9)


def test_jury_veto_rejects_the_candidate_with_its_reason(tmp_path, video_dir, rubric_path):
    proposal = {"moments": [moment(10.25, 44.65), moment(100.25, 134.65)]}
    reason = "diffamation : accuse nommement un developpeur de vol"
    run(
        tmp_path, rubric_path, with_jury(proposal, jury_notes({2: GOOD, 20: GOOD}, vetoes={20: reason})),
        config=auto_config(tmp_path, rubric_path),
    )

    data = read_moments(video_dir)
    assert spans(data) == [(10.2, 44.7)]
    [vetoed] = [r for r in data["rejected"] if r["start"] == 100.2]
    assert "veto" in vetoed["reason"] and "conformite" in vetoed["reason"] and reason in vetoed["reason"]
    assert vetoed["jury"]["veto"] == {"judge": "conformite", "reason": reason}
    # pas de score final : la re-notation apres vision ne peut pas le reprendre
    assert "final_score" not in vetoed


def test_moments_json_holds_the_jury_trace_of_every_candidate(tmp_path, video_dir, rubric_path):
    # l'avocat descend le premier candidat (tout a 1) puis se laisse
    # convaincre au debat ; le second, rejete sous min_score, a aussi sa trace.
    ones = dict.fromkeys(GOOD, 1)
    notes = {2: {**dict.fromkeys(JUDGES, GOOD), "avocat": ones}, 20: WEAK}
    proposal = {"moments": [moment(10.25, 44.65, why="accroche forte"), moment(100.25, 134.65)]}
    fake, _ = run(
        tmp_path, rubric_path, with_jury(proposal, jury_notes(notes, debate={2: {"avocat": GOOD}})),
        config=auto_config(tmp_path, rubric_path),
    )

    assert len(fake.calls) == 1 + 5 + 5  # proposeur, tour 1, debat
    data = read_moments(video_dir)
    assert [j["name"] for j in data["jury"]["judges"]] == ["retention", "spectateur", "monteur", "avocat", "conformite"]
    assert data["jury"]["failed"] == []
    [m] = data["moments"]
    assert m["justification"] == "accroche forte"
    trace = m["jury"]
    assert trace["proposer"] == {"scores": GOOD, "justification": "accroche forte"}
    assert trace["debated"] is True and trace["veto"] is None and trace["score"] == 66.9
    [first, second] = trace["trace"]["rounds"]
    assert set(first["judges"]) == JUDGES
    assert first["judges"]["avocat"]["scores"] == ones
    assert first["judges"]["avocat"]["argument"].startswith("avocat sur C")
    assert second["judges"]["avocat"]["scores"] == GOOD
    assert {(r["judge"], r["criterion"], r["from"], r["to"]) for r in trace["trace"]["revisions"]} >= {
        ("avocat", "hook", 1, 9),
    }
    [low] = [r for r in data["rejected"] if "min_score" in r["reason"]]
    assert low["jury"]["debated"] is False
    assert set(low["jury"]["trace"]["rounds"][0]["judges"]) == JUDGES


def test_review_mode_keeps_the_single_call_by_default(tmp_path, video_dir, rubric_path):
    fake, _ = run(tmp_path, rubric_path, [{"moments": [moment(10.25, 44.65)]}])

    assert [c.usage for c in fake.calls] == ["moments"]
    data = read_moments(video_dir)
    assert data["selection"] == "single"
    assert "jury" not in data and "jury" not in data["moments"][0]


def test_selection_jury_calls_the_jury_in_review_mode(tmp_path, video_dir, rubric_path):
    fake, _ = run(
        tmp_path, rubric_path, with_jury({"moments": [moment(10.25, 44.65)]}, jury_notes({2: WEAK})),
        config=make_config(tmp_path, rubric_path, selection="jury"),
    )

    assert {c.usage for c in fake.calls[1:]} == {f"jury_{j}" for j in JUDGES}
    data = read_moments(video_dir)
    assert data["selection"] == "jury"
    assert data["moments"] == []


def test_auto_mode_uses_the_jury_even_with_selection_single(tmp_path, video_dir, rubric_path):
    # ADR-ff87 : en mode auto, la selection passe toujours par le jury.
    fake, _ = run(
        tmp_path, rubric_path, with_jury({"moments": [moment(10.25, 44.65)]}, jury_notes({2: GOOD})),
        config=auto_config(tmp_path, rubric_path, selection="single"),
    )

    assert len([c for c in fake.calls if c.usage.startswith("jury_")]) == 5
    assert read_moments(video_dir)["selection"] == "jury"


def test_unknown_selection_is_refused(tmp_path, video_dir, rubric_path):
    from clipper.moments import MomentsError

    with pytest.raises(MomentsError, match="selection"):
        run(tmp_path, rubric_path, [{"moments": []}], config=make_config(tmp_path, rubric_path, selection="vote"))
    assert not (video_dir / "moments.json").exists()


def test_invalid_judge_answer_fails_and_writes_nothing(tmp_path, video_dir, rubric_path):
    good = jury_notes({2: GOOD})

    def judges(request):
        return {"candidates": []} if request.usage == "jury_monteur" else good(request)

    with pytest.raises(llm.SchemaError):
        run(
            tmp_path, rubric_path, with_jury({"moments": [moment(10.25, 44.65)]}, judges),
            config=auto_config(tmp_path, rubric_path),
        )
    assert not (video_dir / "moments.json").exists()


def test_long_transcript_with_the_jury_skips_the_comparison_round(tmp_path, video_dir, rubric_path):
    config = auto_config(tmp_path, rubric_path, max_transcript_chars=2000, chunk_chars=2000, chunk_overlap_seconds=30)

    def proposal(request):
        assert "id 0" not in request.prompt, "tour de comparaison appele alors que le jury note"
        if "[10.2-14.7]" in request.prompt:
            return {"moments": [moment(10.25, 44.65, scores=WEAK)]}
        if "[450.2-454.7]" in request.prompt:
            return {"moments": [moment(450.25, 484.65, scores=GOOD)]}
        return {"moments": []}

    fake, _ = run(tmp_path, rubric_path, with_jury(proposal, jury_notes({2: GOOD, 90: WEAK})), config=config)

    jury_calls = [c for c in fake.calls if c.usage != "moments"]
    assert len(jury_calls) == 5
    assert all("mot2_0" in c.prompt and "mot90_0" in c.prompt for c in jury_calls)
    data = read_moments(video_dir)
    assert data["chunked"] is True
    by_start = sorted(data["moments"], key=lambda m: m["start"])
    assert [(m["start"], m["scores"]) for m in by_start] == [(10.2, GOOD), (450.2, WEAK)]


def test_rescore_after_vision_keeps_the_jury_trace_and_the_veto(tmp_path, video_dir, rubric_path):
    config = auto_config(tmp_path, rubric_path)
    proposal = {"moments": [moment(10.25, 44.65), moment(100.25, 134.65)]}
    run(tmp_path, rubric_path, with_jury(proposal, jury_notes({2: GOOD, 20: GOOD}, vetoes={20: "droits"})), config=config)
    trace = read_moments(video_dir)["moments"][0]["jury"]
    write_vision_after_moments(video_dir, [striking(20.0), striking(110.0)])

    fake, _ = rescore(tmp_path, rubric_path, config=config)

    assert fake.calls == []
    data = read_moments(video_dir)
    [m] = data["moments"]
    assert (m["start"], m["final_score"]) == (10.2, 68.9)
    assert m["jury"] == trace
    [vetoed] = [r for r in data["rejected"] if r["start"] == 100.2]
    assert "veto" in vetoed["reason"]


# --------------------------------------------------------------------------
# Integration optionnelle avec le vrai Claude (quota de l'utilisateur) :
# CLIPPER_CLAUDE_INTEGRATION=1 pytest tests/test_moments.py
# --------------------------------------------------------------------------

STORY = [
    "Attendez, attendez, je viens de recevoir un message de ma source chez Rockstar.",
    "Et franchement je ne sais pas si j'ai le droit de le dire en live.",
    "Bon, tant pis, je le dis.",
    "La date de sortie de GTA 6 aurait encore ete repoussee.",
    "Pas de quelques semaines, de six mois.",
    "Le chat est en train d'exploser, regardez-moi ca.",
    "Selon lui, c'est Vice City qui n'est pas pret, la carte est trop grande.",
    "Et Lucia aurait des missions entierement refaites.",
    "Alors vous allez me dire, encore une rumeur.",
    "Sauf que cette source m'avait donne le premier trailer trois jours avant tout le monde.",
    "Donc moi, j'y crois a quatre-vingts pour cent.",
    "Bref, on en reparle quand Rockstar confirme, mais preparez-vous.",
]


@pytest.mark.skipif(
    os.environ.get("CLIPPER_CLAUDE_INTEGRATION") != "1",
    reason="integration Claude : definir CLIPPER_CLAUDE_INTEGRATION=1 (consomme du quota)",
)
def test_real_claude_answers_the_schema_and_bounds_land_on_sentences(tmp_path, video_dir, rubric_path):
    from clipper.moments import run as run_moments

    segments = []
    for k, text in enumerate(STORY):
        words = text.split()
        step = 4.0 / len(words)
        ws = [
            {"word": " " + w, "start": 4.5 * k + i * step, "end": 4.5 * k + (i + 1) * step - 0.05, "probability": 0.9}
            for i, w in enumerate(words)
        ]
        segments.append({"id": k, "start": ws[0]["start"], "end": ws[-1]["end"], "text": text, "words": ws})
    (video_dir / "transcript.json").write_text(json.dumps({"segments": segments}), encoding="utf-8")
    (video_dir / "meta.json").write_text(json.dumps({**META, "chapters": [], "heatmap": [], "sponsorblock_segments": []}), encoding="utf-8")

    run_moments(VIDEO_ID, tmp_path / "workspace", config=make_config(tmp_path, rubric_path))

    data = read_moments(video_dir)
    starts = {math.floor(s["start"] * 10 + 1e-6) / 10 for s in segments}
    ends = {math.ceil(s["end"] * 10 - 1e-6) / 10 for s in segments}
    for m in data["moments"] + [r for r in data["rejected"] if "final_score" in r]:
        assert m["start"] in starts and m["end"] in ends
