from __future__ import annotations

import json
import logging
import random
import threading
import time

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
max_parts = {max_parts}
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
# Une partie qui suit une coupe en 5k + 4.65 reprend donc au debut de la
# phrase k (5k + 0.25), 4.4 s avant la coupe : le debut de phrase le plus
# proche de coupe - 3 s dans [coupe - 8, coupe - 1].
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
# Phrases 20..63 : 100.25 -> 319.65, 219.5 s : 3 ou 4 parties de 60-90 s, reprise comprise.
LONG = moment(1, 100.2, 319.7, "multipart", [{"start": 100.2, "end": 174.7}, {"start": 175.2, "end": 319.7}])
# Phrases 60..73 : 300.25 -> 369.65, 69.5 s : trop long pour un clip, trop court pour 2 parties.
MIDDLE = moment(2, 300.2, 369.7, "multipart")
# Phrases 20..79 : 100.25 -> 399.65, 299.5 s : 4 ou 5 parties.
HUGE = moment(3, 100.2, 399.7, "multipart")
# Phrases 20..91 : 100.25 -> 459.65, 359.5 s : un moment de 6 min.
SIX_MIN = moment(4, 100.2, 459.7, "multipart")
# 246 s : 2 parties de 120 s + 3 s de tolerance bord a bord, mais pas reprise comprise.
S246 = moment(5, 100.2, 346.2, "multipart")
# Phrases 20..55 : 100.25 -> 279.65, 179.5 s : 2 parties tiennent bord a bord
# (coupe en 189.65), plus reprise comprise.
TIGHT = moment(6, 100.2, 279.7, "multipart")


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


def write_transcript(workspace, transcript):
    (workspace / VIDEO_ID / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")


def make_config(tmp_path, single_min=20, single_max=45, part_min=60, part_max=90, max_parts=12, parallel=None):
    rubric = tmp_path / "rubric.toml"
    rubric.write_text(
        TEST_RUBRIC.format(
            single_min=single_min, single_max=single_max, part_min=part_min, part_max=part_max, max_parts=max_parts
        ),
        encoding="utf-8",
    )
    section: dict[str, object] = {"rubric_path": str(rubric)}
    if parallel is not None:
        section["parallel"] = parallel
    return Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={"parts": section},
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


def overlaps(m):
    return [p["overlap"] for p in m["parts"]]


def cuts_range(fake):
    schema = fake.calls[0].schema["properties"]["cuts"]
    return schema["minItems"], schema["maxItems"]


SENTENCE_ENDS = {round(5 * k + 4.65, 2) for k in range(100)}
SENTENCE_STARTS = {round(5 * k + 0.25, 2) for k in range(100)}
WORDS = [(w["start"], w["end"]) for s in make_transcript()["segments"] for w in s["words"]]


def assert_valid(m, moment_, part_min, part_max, tolerance=3):
    """Invariants du critere : la partie 1 commence au debut du moment, la
    derniere finit a sa fin ; chaque coupe est une fin de phrase, jamais dans
    un mot ; la partie suivante commence 1 a 8 s avant, sur un debut de phrase
    (il en existe toujours un dans la fenetre avec cette transcription) ;
    parties, reprise comprise, dans les bornes."""
    parts = m["parts"]
    assert parts[0]["start"] == moment_["start"]
    assert parts[-1]["end"] == moment_["end"]
    assert parts[0]["overlap"] == 0
    for a, b in zip(parts, parts[1:]):
        assert a["end"] - 8 <= b["start"] <= a["end"] - 1, f"reprise hors 1-8 s entre {a} et {b}"
        assert round(b["start"], 2) in SENTENCE_STARTS, f"partie {b} hors debut de phrase"
        assert b["overlap"] == pytest.approx(a["end"] - b["start"], abs=0.01)
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
    assert overlaps(m) == [0]
    assert m["parts"][0]["hook_text"] == "mot2_0 mot2_1 mot2_2 mot2_3 mot2_4."
    assert fake.calls == []


def test_long_moment_is_cut_where_the_llm_says_snapped_to_the_nearest_sentence_end(workspace, tmp_path):
    write_moments(workspace, LONG)
    # 173.0 tombe dans un mot (172.95-173.75) : fins voisines 169.65 et 174.65.
    # 247.3 : fins voisines 244.65 et 249.65. Chaque partie suivante reprend
    # au debut de la derniere phrase de la precedente, 4.4 s avant la coupe.
    fake, _ = run(workspace, make_config(tmp_path), [cuts(173.0, 247.3)])

    assert [c.usage for c in fake.calls] == ["parts"]
    m = by_id(read_parts(workspace), 1)
    assert m["format"] == "multipart"
    assert spans(m) == [(100.2, 174.65), (170.25, 249.65), (245.25, 319.7)]
    assert overlaps(m) == [0, 4.4, 4.4]
    assert [p["suspense"] for p in m["parts"]] == ["suspense a 173.0", "suspense a 247.3", None]
    assert_valid(m, LONG, 60, 90)


def test_six_minute_moment_parts_follow_each_other_with_a_sentence_start_overlap(workspace, tmp_path):
    write_moments(workspace, SIX_MIN)
    run(workspace, make_config(tmp_path, single_min=60, single_max=120, part_min=60, part_max=120),
        [cuts(190.0, 280.0, 370.0)])

    m = by_id(read_parts(workspace), 4)
    assert spans(m) == [(100.2, 189.65), (185.25, 279.65), (275.25, 369.65), (365.25, 459.7)]
    assert overlaps(m) == [0, 4.4, 4.4, 4.4]
    assert_valid(m, SIX_MIN, 60, 120)


def test_prompt_carries_the_moment_transcript_and_the_duration_bounds(workspace, tmp_path):
    write_moments(workspace, LONG)
    fake, _ = run(workspace, make_config(tmp_path), [cuts(173.0, 247.3)])

    prompt = fake.calls[0].prompt
    assert "mot20_0" in prompt and "mot63_4." in prompt
    assert "mot19_0" not in prompt and "mot64_0" not in prompt
    assert "60 a 90 s" in prompt
    assert "suspense" in prompt


def test_prompt_says_parts_follow_each_other_with_an_overlap(workspace, tmp_path):
    write_moments(workspace, LONG)
    fake, _ = run(workspace, make_config(tmp_path), [cuts(173.0, 247.3)])

    prompt = fake.calls[0].prompt
    assert "Partie 1" in prompt and "Partie 2" in prompt
    assert "Part 1" not in prompt
    assert "se suivent" in prompt
    assert "reprend environ 3 s" in prompt


def test_each_part_carries_its_own_hook_text(workspace, tmp_path):
    write_moments(workspace, LONG)
    run(workspace, make_config(tmp_path), [cuts(173.0, 247.3)])

    m = by_id(read_parts(workspace), 1)
    assert [p["hook_text"] for p in m["parts"]] == [
        "mot20_0 mot20_1 mot20_2 mot20_3 mot20_4.",
        "mot34_0 mot34_1 mot34_2 mot34_3 mot34_4.",
        "mot49_0 mot49_1 mot49_2 mot49_3 mot49_4.",
    ]


# --------------------------------------------------------------------------
# Replis de la reprise : transcription faite a la main autour d'une seule
# coupe possible. Phrase A (a0..a39) de 0.2 a 36.1 s, phrase B qui finit la
# partie 1 (la coupe), phrase C (c0..c69) de 65.1 a 128.0 s. Moment 0.2 -> 128
# en parties de 60-90 s : exactement 2 parties, la coupe est la fin de B.
# --------------------------------------------------------------------------


def words_from(start, names, step=0.9, length=0.8):
    return [
        {"word": f" {name}", "start": round(start + i * step, 2), "end": round(start + i * step + length, 2),
         "probability": 0.9}
        for i, name in enumerate(names)
    ]


def sentence(prefix, start, n):
    return words_from(start, [f"{prefix}{i}" + ("." if i == n - 1 else "") for i in range(n)])


def transcript_with_b(b_words):
    segments = []
    for k, words in enumerate([sentence("a", 0.2, 40), b_words, sentence("c", 65.1, 70)]):
        segments.append({"id": k, "start": words[0]["start"], "end": words[-1]["end"],
                         "text": "".join(w["word"] for w in words), "words": words})
    return {"video_id": VIDEO_ID, "language": "fr", "duration": 130.0, "segments": segments}


FALLBACK = moment(7, 0.2, 128.0, "multipart")


def run_fallback(workspace, tmp_path, b_words):
    write_transcript(workspace, transcript_with_b(b_words))
    write_moments(workspace, FALLBACK)
    run(workspace, make_config(tmp_path), [cuts(64.0)])
    return by_id(read_parts(workspace), 7)


def test_without_sentence_start_in_the_window_the_part_resumes_on_the_closest_word_start(workspace, tmp_path):
    # B : b0..b30 de 36.7 a 64.5 s, aucun debut de phrase dans [56.5, 63.5] ;
    # debuts de mot 61.0 et 61.9 autour de 64.5 - 3 = 61.5 : 61.9 est le plus proche.
    m = run_fallback(workspace, tmp_path, sentence("b", 36.7, 31))

    assert spans(m) == [(0.2, 64.5), (61.9, 128.0)]
    assert overlaps(m) == [0, 2.6]
    assert m["parts"][1]["hook_text"] == "b28 b29 b30."


def test_without_word_start_in_the_window_the_part_resumes_on_the_last_word_before_the_cut(workspace, tmp_path):
    # B : b0..b19 de 36.7 a 54.6 s, 9.4 s de silence, puis "fin." de 64.0 a 64.5 :
    # aucun debut de mot dans [56.5, 63.5], reprise de 0.5 s (< part_overlap_min).
    b = sentence("b", 36.7, 20)
    b[-1]["word"] = " b19"
    b.append({"word": " fin.", "start": 64.0, "end": 64.5, "probability": 0.9})
    m = run_fallback(workspace, tmp_path, b)

    assert spans(m) == [(0.2, 64.5), (64.0, 128.0)]
    assert overlaps(m) == [0, 0.5]
    assert m["parts"][1]["hook_text"] == "fin."


def test_without_any_word_start_to_resume_on_the_part_starts_on_the_first_word_after_the_cut(
    workspace, tmp_path, caplog
):
    # B : b0..b19, puis un mot de 55.0 a 64.5 s : aucun debut de mot dans
    # [56.5, 64.5[, la partie 2 commence au premier mot apres la coupe (65.1),
    # jamais sur le silence de tete : reprise nulle, journalisee.
    b = sentence("b", 36.7, 20)
    b[-1]["word"] = " b19"
    b.append({"word": " fiiiin.", "start": 55.0, "end": 64.5, "probability": 0.9})
    with caplog.at_level(logging.WARNING, logger="clipper.parts"):
        m = run_fallback(workspace, tmp_path, b)

    assert spans(m) == [(0.2, 64.5), (65.1, 128.0)]
    assert overlaps(m) == [0, 0]
    assert m["parts"][1]["hook_text"].startswith("c0 c1 ")
    assert any("reprise nulle" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------
# Bornes
# --------------------------------------------------------------------------


def test_out_of_bounds_proposal_is_moved_to_the_nearest_feasible_sentence_end(workspace, tmp_path):
    write_moments(workspace, LONG)
    # Premiere partie de 10 s : impossible, la coupe glisse jusqu'a la fin de
    # phrase faisable la plus proche (>= 100.2 + 60 - 3 de tolerance). La
    # partie 2 reprend en 155.25 : finir en 249.65 lui ferait 94.4 s, elle
    # finit en 244.65.
    run(workspace, make_config(tmp_path), [cuts(110.0, 248.0)])

    m = by_id(read_parts(workspace), 1)
    assert spans(m) == [(100.2, 159.65), (155.25, 244.65), (240.25, 319.7)]
    assert_valid(m, LONG, 60, 90)


def test_bounds_come_from_the_rubric(workspace, tmp_path):
    write_moments(workspace, LONG)
    # Parties de 100-120 s : 219.5 s ne se coupe qu'en deux.
    fake, _ = run(workspace, make_config(tmp_path, part_min=100, part_max=120), [cuts(210.0)])

    assert cuts_range(fake) == (1, 1)
    m = by_id(read_parts(workspace), 1)
    assert spans(m) == [(100.2, 209.65), (205.25, 319.7)]
    assert_valid(m, LONG, 100, 120)


def test_246_s_is_cut_in_3_parts_because_2_do_not_fit_with_the_overlap(workspace, tmp_path):
    write_moments(workspace, S246)
    config = make_config(tmp_path, single_min=60, single_max=120, part_min=60, part_max=120)
    fake, _ = run(workspace, config, [cuts(180.0, 265.0)])

    assert cuts_range(fake) == (2, 3)
    m = by_id(read_parts(workspace), 5)
    assert spans(m) == [(100.2, 179.65), (175.25, 264.65), (260.25, 346.2)]
    assert overlaps(m) == [0, 4.4, 4.4]

    with pytest.raises(llm.SchemaError):
        run(workspace, config, [cuts(180.0)], force=True)


def test_number_of_parts_is_capped_by_max_parts(workspace, tmp_path):
    write_moments(workspace, HUGE)
    # 299.5 s en parties de 60-90 s : 4 ou 5 parties, 4 au plus avec max_parts = 4.
    fake, _ = run(workspace, make_config(tmp_path, max_parts=4), [cuts(170.0, 245.0, 320.0)])
    assert cuts_range(fake) == (3, 3)
    assert by_id(read_parts(workspace), 3)["parts_total"] == 4

    with pytest.raises(llm.SchemaError):
        run(workspace, make_config(tmp_path, max_parts=4), [cuts(160.0, 220.0, 280.0, 340.0)], force=True)


def test_moment_needing_more_than_max_parts_is_rejected_with_a_reason(workspace, tmp_path):
    write_moments(workspace, S246)
    config = make_config(tmp_path, single_min=60, single_max=120, part_min=60, part_max=120, max_parts=2)
    fake, _ = run(workspace, config, [])

    data = read_parts(workspace)
    assert data["moments"] == []
    assert [r["id"] for r in data["rejected"]] == [5]
    assert "246.0" in data["rejected"][0]["reason"]
    assert "2 a 2 parties" in data["rejected"][0]["reason"]
    assert fake.calls == []


def test_cuts_that_fit_only_without_the_overlap_are_rejected_with_a_reason(workspace, tmp_path):
    write_moments(workspace, TIGHT)
    fake, _ = run(workspace, make_config(tmp_path), [cuts(189.0)])

    data = read_parts(workspace)
    assert data["moments"] == []
    assert [r["id"] for r in data["rejected"]] == [6]
    assert "reprise" in data["rejected"][0]["reason"]


def test_llm_proposing_an_impossible_number_of_parts_is_a_failure(workspace, tmp_path):
    write_moments(workspace, LONG)
    # 219.5 s en parties de 60-90 s, reprise comprise : 3 ou 4 parties, donc 2 ou 3 coupes.
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
# Grille et reglages
# --------------------------------------------------------------------------


def test_max_parts_is_required_in_the_rubric(workspace, tmp_path):
    from clipper.parts import PartsError, load_durations

    rubric = tmp_path / "rubric.toml"
    rubric.write_text(
        TEST_RUBRIC.format(single_min=20, single_max=45, part_min=60, part_max=90, max_parts=12).replace(
            "max_parts = 12\n", ""
        ),
        encoding="utf-8",
    )
    with pytest.raises(PartsError, match="max_parts"):
        load_durations(rubric)


def test_overlap_settings_have_their_defaults():
    from clipper.parts import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["part_overlap_seconds"] == 3
    assert CONFIG_DEFAULTS["part_overlap_min"] == 1
    assert CONFIG_DEFAULTS["part_overlap_max"] == 8


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


# --------------------------------------------------------------------------
# Parallelisation des moments (TASK-ed18)
# --------------------------------------------------------------------------


class ConcurrencyBackend:
    """Backend de test qui journalise le chevauchement des appels concurrents
    et sert toujours la meme reponse (``response``, un dict JSON-able) ;
    ``delays`` donne le temps de pause (s) du n-ieme appel a demarrer (le
    dernier de la liste sert pour les appels suivants), sinon 0.05 s fixe."""

    def __init__(self, response, delays=None):
        self.response = response
        self.delays = list(delays) if delays is not None else None
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls: list[Any] = []

    def complete(self, request):
        with self.lock:
            index = len(self.calls)
            self.calls.append(request)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        if self.delays:
            delay = self.delays[min(index, len(self.delays) - 1)]
        else:
            delay = 0.05
        time.sleep(delay)
        with self.lock:
            self.active -= 1
        return json.dumps(self.response)


class FailOnceBackend:
    """Backend de test qui echoue exactement au n-ieme appel a atteindre le
    verrou (``fail_after``, 1-indexe), quel que soit le moment concerne."""

    def __init__(self, response, fail_after):
        self.response = response
        self.fail_after = fail_after
        self.lock = threading.Lock()
        self.count = 0

    def complete(self, request):
        with self.lock:
            self.count += 1
            should_fail = self.count == self.fail_after
        if should_fail:
            raise llm.TransientLLMError("quota")
        return json.dumps(self.response)


def run_with_backend(workspace, config, backend, **kwargs):
    from clipper.parts import run as run_parts

    with llm.use_backend(backend):
        path = run_parts(VIDEO_ID, workspace, config=config, **kwargs)
    return path


def test_parallel_default_is_4():
    from clipper.parts import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["parallel"] == 4


def test_parallel_below_1_is_refused(workspace, tmp_path):
    from clipper.parts import PartsError

    write_moments(workspace, SHORT)
    with pytest.raises(PartsError, match="parallel"):
        run(workspace, make_config(tmp_path, parallel=0), [])


def test_moments_overlap_when_parallel_is_4(workspace, tmp_path):
    moments = [moment(40 + i, 100.2, 319.7, "multipart") for i in range(4)]
    write_moments(workspace, *moments)
    backend = ConcurrencyBackend(cuts(173.0, 247.3))

    run_with_backend(workspace, make_config(tmp_path, parallel=4), backend)

    assert len(backend.calls) == 4
    assert backend.max_active >= 2


def test_moments_never_overlap_when_parallel_is_1(workspace, tmp_path):
    moments = [moment(30 + i, 100.2, 319.7, "multipart") for i in range(4)]
    write_moments(workspace, *moments)
    backend = ConcurrencyBackend(cuts(173.0, 247.3))

    run_with_backend(workspace, make_config(tmp_path, parallel=1), backend)

    assert len(backend.calls) == 4
    assert backend.max_active == 1


def test_output_is_identical_between_parallel_1_and_4_even_out_of_order(workspace, tmp_path):
    ids = [50, 51, 52, 53]
    moments = [moment(i, 100.2, 319.7, "multipart") for i in ids]
    write_moments(workspace, *moments)

    backend_seq = ConcurrencyBackend(cuts(173.0, 247.3))
    run_with_backend(workspace, make_config(tmp_path, parallel=1), backend_seq)
    sequential = read_parts(workspace)

    # Le premier appel a demarrer est le plus lent, le dernier le plus
    # rapide : les reponses arrivent dans le desordre.
    backend_par = ConcurrencyBackend(cuts(173.0, 247.3), delays=[0.2, 0.15, 0.1, 0.05])
    run_with_backend(workspace, make_config(tmp_path, parallel=4), backend_par, force=True)
    parallel = read_parts(workspace)

    assert sequential == parallel
    assert [m["id"] for m in parallel["moments"]] == ids


def test_a_failing_moment_propagates_and_writes_nothing_in_parallel(workspace, tmp_path):
    moments = [moment(60 + i, 100.2, 319.7, "multipart") for i in range(4)]
    write_moments(workspace, *moments)
    backend = FailOnceBackend(cuts(173.0, 247.3), fail_after=2)

    with pytest.raises(llm.TransientLLMError):
        run_with_backend(workspace, make_config(tmp_path, parallel=4), backend)
    assert not (workspace / VIDEO_ID / "parts.json").exists()
