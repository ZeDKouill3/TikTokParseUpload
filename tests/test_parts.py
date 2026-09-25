from __future__ import annotations

import json
import random

import pytest

from clipper import llm
from clipper.config import Config
from clipper.llm.fake import FakeBackend

VIDEO_ID = "abcdefghijk"

# Grille de test figee : seules les durees servent a l'etape parts.
TEST_RUBRIC = """
min_score = 60
trend_keywords = []

[criteria.hook]
weight = 1
question = "Accroche ?"

[durations]
single_min = {single_min}
single_max = {single_max}
part_min = {part_min}
part_max = {part_max}
min_parts = 2
tolerance = 3

[bonus]
max_total = 0
replayed = 0
audio_peaks = 0
audio_peaks_full = 1
visual = 0

[exclusions]
sponsorblock_categories = []
"""


# --------------------------------------------------------------------------
# Fixtures : 100 phrases de 5 mots ; la phrase k va de 5k + 0.25 s a
# 5k + 4.65 s (fin du dernier mot), 0.6 s de pause entre deux. Les mots font
# 0.8 s, espaces de 0.1 s. Fins de phrase : 4.65, 9.65, ..., 5k + 4.65.
# --------------------------------------------------------------------------


def make_transcript(n=100):
    segments = []
    for k in range(n):
        words = []
        for i in range(5):
            start = 5 * k + 0.25 + i * 0.9
            text = f" mot{k}_{i}" + ("." if i == 4 else "")
            words.append({"word": text, "start": round(start, 2), "end": round(start + 0.8, 2), "probability": 0.9})
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


def moment(id_, start, end, fmt="single", parts=()):
    """Un moment tel que l'ecrit clipper/moments.py dans moments.json."""
    return {
        "id": id_,
        "start": start,
        "end": end,
        "duration": round(end - start, 1),
        "format": fmt,
        "parts": list(parts),
        "scores": {"hook": 8},
        "bonus": {"replayed": 0.0, "audio_peaks": 0.0, "visual": 0.0, "total": 0.0},
        "final_score": 80.0,
        "justification": "ca marche",
        "hook_text": "accroche",
    }


# Phrases 2..7 : 10.25 -> 39.65, arrondi comme moments.py (floor/ceil au dixieme).
SHORT = moment(0, 10.2, 39.7)
# Phrases 20..63 : 100.25 -> 319.65, 219.5 s : 3 parties exactement.
LONG = moment(1, 100.2, 319.7, "multipart", [{"start": 100.2, "end": 174.7}, {"start": 175.2, "end": 319.7}])
# Phrases 60..73 : 300.25 -> 369.65, 69.5 s : trop long pour un clip, trop court pour 2 parties.
MIDDLE = moment(2, 300.2, 369.7, "multipart")
# Phrases 20..79 : 100.25 -> 399.65, 299.5 s : 4 ou 5 parties.
HUGE = moment(3, 100.2, 399.7, "multipart")


def moments_json(*moments):
    return {"video_id": VIDEO_ID, "rubric": {}, "chunked": False, "moments": list(moments), "rejected": []}


@pytest.fixture
def workspace(tmp_path):
    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / "transcript.json").write_text(json.dumps(make_transcript()), encoding="utf-8")
    return tmp_path / "workspace"


def write_moments(workspace, *moments):
    (workspace / VIDEO_ID / "moments.json").write_text(json.dumps(moments_json(*moments)), encoding="utf-8")


def make_config(tmp_path, single_min=20, single_max=45, part_min=60, part_max=90):
    rubric = tmp_path / "rubric.toml"
    rubric.write_text(
        TEST_RUBRIC.format(single_min=single_min, single_max=single_max, part_min=part_min, part_max=part_max),
        encoding="utf-8",
    )
    return Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={"parts": {"rubric_path": str(rubric)}},
    )


def cuts(*times):
    return {"cuts": [{"at": t, "suspense": f"suspense a {t}"} for t in times]}


def run(workspace, config, responses, **kwargs):
    from clipper.parts import run as run_parts

    fake = FakeBackend(responses)
    with llm.use_backend(fake):
        path = run_parts(VIDEO_ID, workspace, config=config, **kwargs)
    return fake, path


def read_parts(workspace):
    return json.loads((workspace / VIDEO_ID / "parts.json").read_text(encoding="utf-8"))


def by_id(data, id_):
    return next(m for m in data["moments"] if m["id"] == id_)


def spans(m):
    return [(p["start"], p["end"]) for p in m["parts"]]


SENTENCE_ENDS = {round(5 * k + 4.65, 2) for k in range(100)}
WORDS = [(w["start"], w["end"]) for s in make_transcript()["segments"] for w in s["words"]]


def assert_valid(m, moment_, part_min, part_max, tolerance=3):
    """Invariants du critere : couverture exacte sans trou ni chevauchement,
    coupes en fin de phrase et jamais dans un mot, parties dans les bornes."""
    parts = m["parts"]
    assert parts[0]["start"] == moment_["start"]
    assert parts[-1]["end"] == moment_["end"]
    for a, b in zip(parts, parts[1:]):
        assert a["end"] == b["start"], f"trou ou chevauchement entre {a} et {b}"
    for p in parts[:-1]:
        assert round(p["end"], 2) in SENTENCE_ENDS, f"coupe {p['end']} hors fin de phrase"
        assert not any(ws < p["end"] < we for ws, we in WORDS), f"coupe {p['end']} au milieu d'un mot"
    for p in parts:
        d = p["end"] - p["start"]
        assert part_min - tolerance <= d <= part_max + tolerance, f"partie {p} hors bornes"
        assert p["duration"] == pytest.approx(d, abs=0.01)
    assert [p["part"] for p in parts] == list(range(1, len(parts) + 1))
    assert m["parts_total"] == len(parts)


# --------------------------------------------------------------------------
# Clip unique ou N parties
# --------------------------------------------------------------------------


def test_short_moment_is_a_single_clip_without_calling_the_llm(workspace, tmp_path):
    write_moments(workspace, SHORT)
    fake, path = run(workspace, make_config(tmp_path), [])

    assert path == workspace / VIDEO_ID / "parts.json"
    m = by_id(read_parts(workspace), 0)
    assert m["format"] == "single"
    assert m["parts_total"] == 1
    assert spans(m) == [(10.2, 39.7)]
    assert fake.calls == []


def test_long_moment_is_cut_where_the_llm_says_snapped_to_the_nearest_sentence_end(workspace, tmp_path):
    write_moments(workspace, LONG)
    # 173.0 tombe dans un mot (172.95-173.75) : fins voisines 169.65 et 174.65.
    # 247.3 : fins voisines 244.65 et 249.65.
    fake, _ = run(workspace, make_config(tmp_path), [cuts(173.0, 247.3)])

    assert [c.usage for c in fake.calls] == ["parts"]
    m = by_id(read_parts(workspace), 1)
    assert m["format"] == "multipart"
    assert spans(m) == [(100.2, 174.65), (174.65, 249.65), (249.65, 319.7)]
    assert [p["suspense"] for p in m["parts"]] == ["suspense a 173.0", "suspense a 247.3", None]
    assert_valid(m, LONG, 60, 90)


def test_prompt_carries_the_moment_transcript_and_the_duration_bounds(workspace, tmp_path):
    write_moments(workspace, LONG)
    fake, _ = run(workspace, make_config(tmp_path), [cuts(173.0, 247.3)])

    prompt = fake.calls[0].prompt
    assert "mot20_0" in prompt and "mot63_4." in prompt
    assert "mot19_0" not in prompt and "mot64_0" not in prompt
    assert "60 a 90 s" in prompt
    assert "suspense" in prompt


def test_each_part_carries_its_own_hook_text(workspace, tmp_path):
    write_moments(workspace, LONG)
    run(workspace, make_config(tmp_path), [cuts(173.0, 247.3)])

    m = by_id(read_parts(workspace), 1)
    assert [p["hook_text"] for p in m["parts"]] == [
        "mot20_0 mot20_1 mot20_2 mot20_3 mot20_4.",
        "mot35_0 mot35_1 mot35_2 mot35_3 mot35_4.",
        "mot50_0 mot50_1 mot50_2 mot50_3 mot50_4.",
    ]


# --------------------------------------------------------------------------
# Bornes
# --------------------------------------------------------------------------


def test_out_of_bounds_proposal_is_moved_to_the_nearest_feasible_sentence_end(workspace, tmp_path):
    write_moments(workspace, LONG)
    # Premiere partie de 10 s : impossible, la coupe glisse jusqu'a la fin de
    # phrase faisable la plus proche (>= 100.2 + 60 - 3 de tolerance).
    run(workspace, make_config(tmp_path), [cuts(110.0, 250.0)])

    m = by_id(read_parts(workspace), 1)
    assert spans(m) == [(100.2, 159.65), (159.65, 249.65), (249.65, 319.7)]
    assert_valid(m, LONG, 60, 90)


def test_bounds_come_from_the_rubric(workspace, tmp_path):
    write_moments(workspace, LONG)
    # Parties de 100-120 s : 219.5 s ne se coupe qu'en deux.
    fake, _ = run(workspace, make_config(tmp_path, part_min=100, part_max=120), [cuts(210.0)])

    m = by_id(read_parts(workspace), 1)
    assert spans(m) == [(100.2, 209.65), (209.65, 319.7)]
    assert_valid(m, LONG, 100, 120)


def test_llm_proposing_an_impossible_number_of_parts_is_a_failure(workspace, tmp_path):
    write_moments(workspace, LONG)
    # 219.5 s en parties de 60-90 s : exactement 3 parties, donc 2 coupes.
    with pytest.raises(llm.SchemaError):
        run(workspace, make_config(tmp_path), [cuts(210.0)])
    assert not (workspace / VIDEO_ID / "parts.json").exists()


def test_moment_that_fits_neither_format_is_rejected_with_a_reason(workspace, tmp_path):
    write_moments(workspace, SHORT, MIDDLE)
    fake, _ = run(workspace, make_config(tmp_path), [])

    data = read_parts(workspace)
    assert [m["id"] for m in data["moments"]] == [0]
    assert len(data["rejected"]) == 1
    rejected = data["rejected"][0]
    assert rejected["id"] == 2
    assert "69.5" in rejected["reason"]
    assert fake.calls == []


@pytest.mark.parametrize("seed", range(40))
def test_any_proposal_yields_parts_in_bounds_covering_the_moment(workspace, tmp_path, seed):
    rng = random.Random(seed)
    write_moments(workspace, HUGE)
    n_cuts = rng.choice([3, 4])
    proposal = sorted(round(rng.uniform(100.3, 399.6), 2) for _ in range(n_cuts))
    run(workspace, make_config(tmp_path), [cuts(*proposal)], force=True)

    m = by_id(read_parts(workspace), 3)
    assert m["parts_total"] == n_cuts + 1
    assert_valid(m, HUGE, 60, 90)


# --------------------------------------------------------------------------
# Sortie, cache, echecs
# --------------------------------------------------------------------------


def test_existing_result_is_not_redone_unless_forced(workspace, tmp_path):
    write_moments(workspace, SHORT, LONG)
    config = make_config(tmp_path)
    run(workspace, config, [cuts(173.0, 247.3)])

    fake, _ = run(workspace, config, [])
    assert fake.calls == []

    fake, _ = run(workspace, config, [cuts(173.0, 247.3)], force=True)
    assert len(fake.calls) == 1
    data = read_parts(workspace)
    assert data["video_id"] == VIDEO_ID
    assert [m["id"] for m in data["moments"]] == [0, 1]


def test_invalid_llm_answer_writes_nothing(workspace, tmp_path):
    write_moments(workspace, LONG)
    with pytest.raises(llm.SchemaError):
        run(workspace, make_config(tmp_path), [{"cuts": [{"at": "ici"}]}])
    assert not (workspace / VIDEO_ID / "parts.json").exists()


def test_unavailable_llm_propagates_and_writes_nothing(workspace, tmp_path):
    write_moments(workspace, LONG)
    with pytest.raises(llm.TransientLLMError):
        run(workspace, make_config(tmp_path), [llm.TransientLLMError("quota")])
    assert not (workspace / VIDEO_ID / "parts.json").exists()


def test_missing_moments_is_an_error(workspace, tmp_path):
    from clipper.parts import PartsError

    with pytest.raises(PartsError, match="moments.json"):
        run(workspace, make_config(tmp_path), [])


def test_default_rubric_path_is_the_repo_rubric():
    from clipper.parts import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["rubric_path"] == "rubric.toml"
