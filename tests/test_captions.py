from __future__ import annotations

import json

import pytest

from clipper import llm
from clipper.config import Config
from clipper.llm.fake import FakeBackend

VIDEO_ID = "abcdefghijk"


# --------------------------------------------------------------------------
# Transcription de test : deux phrases de 4 mots, 0.0-3.9 s puis 5.0-8.9 s.
# --------------------------------------------------------------------------


def make_transcript(language="fr"):
    def words(base, tokens):
        return [
            {"word": f" {tok}", "start": round(base + i, 2), "end": round(base + i + 0.9, 2), "probability": 0.9}
            for i, tok in enumerate(tokens)
        ]

    segments = [
        {"id": 0, "start": 0.0, "end": 3.9, "text": " alpha beta gamma delta",
         "words": words(0.0, ["alpha", "beta", "gamma", "delta"])},
        {"id": 1, "start": 5.0, "end": 8.9, "text": " epsilon zeta eta theta",
         "words": words(5.0, ["epsilon", "zeta", "eta", "theta"])},
    ]
    return {
        "video_id": VIDEO_ID, "language": language, "language_probability": 0.99,
        "duration": 10.0, "model": "small", "vocab": [], "segments": segments,
    }


def moment(id_, justification="ca marche", hook_text="accroche du moment"):
    """Un moment tel que l'ecrit clipper/moments.py dans moments.json."""
    return {
        "id": id_, "start": 0.0, "end": 8.9, "duration": 8.9, "format": "multipart", "parts": [],
        "scores": {"hook": 8}, "bonus": {"replayed": 0.0, "audio_peaks": 0.0, "visual": 0.0, "total": 0.0},
        "final_score": 80.0, "justification": justification, "hook_text": hook_text,
    }


def moments_json(*moments):
    return {"video_id": VIDEO_ID, "rubric": {}, "chunked": False, "moments": list(moments), "rejected": []}


def part(n, start, end, hook_text="accroche", suspense=None):
    return {"part": n, "start": start, "end": end, "duration": round(end - start, 2),
            "hook_text": hook_text, "suspense": suspense}


def parts_record(id_, fmt, parts_total, parts):
    return {"id": id_, "start": parts[0]["start"], "end": parts[-1]["end"],
            "duration": round(parts[-1]["end"] - parts[0]["start"], 2), "format": fmt,
            "parts_total": parts_total, "proposed_cuts": [], "parts": parts}


def parts_json(*moments, rejected=()):
    return {"video_id": VIDEO_ID, "rubric": {"path": "rubric.toml", "durations": {}},
            "moments": list(moments), "rejected": list(rejected)}


@pytest.fixture
def workspace(tmp_path):
    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / "transcript.json").write_text(json.dumps(make_transcript()), encoding="utf-8")
    return tmp_path / "workspace"


def write_moments(workspace, *moments):
    (workspace / VIDEO_ID / "moments.json").write_text(json.dumps(moments_json(*moments)), encoding="utf-8")


def write_parts(workspace, *moments, rejected=()):
    (workspace / VIDEO_ID / "parts.json").write_text(
        json.dumps(parts_json(*moments, rejected=rejected)), encoding="utf-8"
    )


def write_meta(workspace, title="Une video"):
    (workspace / VIDEO_ID / "meta.json").write_text(json.dumps({"title": title}), encoding="utf-8")


def make_config(tmp_path, **captions_overrides):
    return Config(
        mode="review", workspace_dir=tmp_path / "workspace", output_dir=tmp_path / "output",
        _sections={"captions": captions_overrides} if captions_overrides else {},
    )


def answer(title="Titre choc", caption="Une legende qui donne envie.", hashtags=("#un", "#deux"),
           hook_text="quatre mots pour accrocher", screen_title="Info choc \U0001F525",
           include_screen_title=True, include_title=True):
    result = {"caption": caption, "hashtags": list(hashtags), "hook_text": hook_text}
    if include_title:
        result["title"] = title
    if include_screen_title:
        result["screen_title"] = screen_title
    return result


def run(workspace, config, responses, **kwargs):
    from clipper.captions import run as run_captions

    fake = FakeBackend(responses)
    with llm.use_backend(fake):
        path = run_captions(VIDEO_ID, workspace, config=config, **kwargs)
    return fake, path


def read_captions(workspace):
    return json.loads((workspace / VIDEO_ID / "captions.json").read_text(encoding="utf-8"))


def by_id(data, id_):
    return next(c for c in data["clips"] if c["id"] == id_)


# --------------------------------------------------------------------------
# Un clip par partie
# --------------------------------------------------------------------------


def test_single_clip_gets_title_caption_hashtags_and_hook_text_from_the_llm(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))

    fake, path = run(workspace, make_config(tmp_path), [answer()])

    assert path == workspace / VIDEO_ID / "captions.json"
    assert [c.usage for c in fake.calls] == ["captions"]
    clip = by_id(read_captions(workspace), "00")
    assert clip["title"] == "Titre choc"
    assert clip["caption"] == "Une legende qui donne envie."
    assert clip["hashtags"] == ["#un", "#deux"]
    assert clip["hook_text"] == "quatre mots pour accrocher"
    assert clip["screen_title"] == "Info choc \U0001F525"
    assert clip["moment_id"] == 0 and clip["part"] == 1 and clip["parts_total"] == 1
    assert clip["start"] == 0.0 and clip["end"] == 3.9
    assert clip["language"] == "fr"


def test_multipart_moment_produces_one_clip_per_part_with_context(workspace, tmp_path):
    write_moments(workspace, moment(0, justification="histoire en 2 actes"))
    write_parts(
        workspace, parts_record(0, "multipart", 2, [part(1, 0.0, 3.9, suspense="a suivre"), part(2, 5.0, 8.9)])
    )

    fake, _ = run(
        workspace, make_config(tmp_path),
        [answer(title="Grosse histoire"), answer(include_title=False, include_screen_title=False)],
    )

    data = read_captions(workspace)
    assert [c["id"] for c in data["clips"]] == ["00-p1", "00-p2"]
    assert [c["title"] for c in data["clips"]] == ["Grosse histoire (Partie 1)", "Grosse histoire (Partie 2)"]
    assert all(c["parts_total"] == 2 for c in data["clips"])
    assert [c["part"] for c in data["clips"]] == [1, 2]
    assert len(fake.calls) == 2
    assert "1/2" in fake.calls[0].prompt
    assert "2/2" in fake.calls[1].prompt


def test_prompt_carries_language_video_title_justification_and_part_text(workspace, tmp_path):
    write_moments(workspace, moment(0, justification="parce que oui"))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    write_meta(workspace, title="Ma super video")

    fake, _ = run(workspace, make_config(tmp_path), [answer()])

    prompt = fake.calls[0].prompt
    assert "fr" in prompt
    assert "Ma super video" in prompt
    assert "parce que oui" in prompt
    assert "alpha" in prompt and "beta" in prompt and "gamma" in prompt and "delta" in prompt
    assert "epsilon" not in prompt


def test_meta_json_is_optional(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))

    fake, path = run(workspace, make_config(tmp_path), [answer()])

    assert path.exists()
    assert fake.calls[0].usage == "captions"


def test_no_kept_moment_writes_empty_clips_without_calling_the_llm(workspace, tmp_path):
    write_moments(workspace)
    write_parts(workspace, rejected=[{"id": 0, "start": 0.0, "end": 1.0, "duration": 1.0, "reason": "trop court"}])

    fake, _ = run(workspace, make_config(tmp_path), [])

    assert read_captions(workspace)["clips"] == []
    assert fake.calls == []


# --------------------------------------------------------------------------
# Validation de la reponse (SPEC-6127) : longueurs, hashtags, doublons
# --------------------------------------------------------------------------


def test_hashtag_without_hash_prefix_is_a_failure_and_writes_nothing(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))

    with pytest.raises(llm.SchemaError, match="#"):
        run(workspace, make_config(tmp_path), [answer(hashtags=["sansdiese"])] * 2)
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_duplicate_hashtags_case_insensitive_is_a_failure(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))

    with pytest.raises(llm.SchemaError, match="double"):
        run(workspace, make_config(tmp_path), [answer(hashtags=["#Viral", "#viral"])] * 2)
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_hook_text_over_the_word_limit_is_a_failure(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    nine_words = "un deux trois quatre cinq six sept huit neuf"

    with pytest.raises(llm.SchemaError, match="9 mots"):
        run(workspace, make_config(tmp_path), [answer(hook_text=nine_words)] * 2)
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_refused_hook_text_is_sent_back_to_the_llm_with_the_error_and_repaired(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    ten_words = "un deux trois quatre cinq six sept huit neuf dix"

    fake, _ = run(workspace, make_config(tmp_path),
                  [answer(hook_text=ten_words), answer(hook_text="trois mots courts")])

    assert len(fake.calls) == 2
    assert f"texte d'accroche de 10 mots, 8 au plus : {ten_words!r}" in fake.calls[1].prompt
    assert by_id(read_captions(workspace), "00")["hook_text"] == "trois mots courts"


def test_refused_hashtags_are_repaired_the_same_way(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))

    fake, _ = run(workspace, make_config(tmp_path),
                  [answer(hashtags=["#Viral", "#viral"]), answer(hashtags=["#viral", "#drole"])])

    assert "hashtag en double : '#viral'" in fake.calls[1].prompt
    assert by_id(read_captions(workspace), "00")["hashtags"] == ["#viral", "#drole"]


def test_hook_text_exactly_at_the_word_limit_is_accepted(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    eight_words = "un deux trois quatre cinq six sept huit"

    run(workspace, make_config(tmp_path), [answer(hook_text=eight_words)])

    assert by_id(read_captions(workspace), "00")["hook_text"] == eight_words


def test_hook_text_with_isolated_punctuation_is_counted_by_real_words(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    eight_words_with_colon = "La nouvelle mode : ils se volent entre eux"

    run(workspace, make_config(tmp_path), [answer(hook_text=eight_words_with_colon)])

    assert by_id(read_captions(workspace), "00")["hook_text"] == eight_words_with_colon


def test_hook_text_apostrophe_and_hyphen_words_count_as_one_each(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    six_words_various_punctuation = "l'heure du crime ; vraiment ? — peut-être … non !"

    run(workspace, make_config(tmp_path), [answer(hook_text=six_words_various_punctuation)])

    assert by_id(read_captions(workspace), "00")["hook_text"] == six_words_various_punctuation


def test_hook_words_max_is_configurable(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    three_words = "un deux trois"

    with pytest.raises(llm.SchemaError, match="2 au plus"):
        run(workspace, make_config(tmp_path, hook_words_max=2), [answer(hook_text=three_words)] * 2)


def test_schema_rejects_a_response_missing_a_required_field(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    bad = {"title": "t", "caption": "c", "hashtags": ["#a"]}  # hook_text manquant

    with pytest.raises(llm.SchemaError):
        run(workspace, make_config(tmp_path), [bad, bad])
    assert not (workspace / VIDEO_ID / "captions.json").exists()


# --------------------------------------------------------------------------
# Echecs, cache, entrees manquantes (ADR-ad2e : jamais de repli silencieux)
# --------------------------------------------------------------------------


def test_llm_unavailable_propagates_and_writes_nothing(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))

    with pytest.raises(llm.TransientLLMError):
        run(workspace, make_config(tmp_path), [llm.TransientLLMError("quota")])
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_second_part_failing_still_writes_nothing_for_the_first(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(
        workspace, parts_record(0, "multipart", 2, [part(1, 0.0, 3.9), part(2, 5.0, 8.9)])
    )

    with pytest.raises(llm.TransientLLMError):
        run(workspace, make_config(tmp_path), [answer(), llm.TransientLLMError("quota")])
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_existing_result_is_not_redone_unless_forced(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    config = make_config(tmp_path)
    run(workspace, config, [answer()])

    fake, _ = run(workspace, config, [])
    assert fake.calls == []

    fake, _ = run(workspace, config, [answer(title="Refait")], force=True)
    assert len(fake.calls) == 1
    assert by_id(read_captions(workspace), "00")["title"] == "Refait"


def test_missing_parts_json_is_an_error(workspace, tmp_path):
    from clipper.captions import CaptionsError

    write_moments(workspace, moment(0))
    with pytest.raises(CaptionsError, match="parts.json"):
        run(workspace, make_config(tmp_path), [])


def test_missing_moments_json_is_an_error(workspace, tmp_path):
    from clipper.captions import CaptionsError

    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    with pytest.raises(CaptionsError, match="moments.json"):
        run(workspace, make_config(tmp_path), [])


def test_part_moment_missing_from_moments_json_is_an_error(workspace, tmp_path):
    from clipper.captions import CaptionsError

    write_moments(workspace)  # aucun moment
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))

    with pytest.raises(CaptionsError, match="moments.json"):
        run(workspace, make_config(tmp_path), [])


def test_default_config_values():
    from clipper.captions import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["hashtags_max"] == 8
    assert CONFIG_DEFAULTS["hook_words_max"] == 8
    assert CONFIG_DEFAULTS["title_max_chars"] == 100
    assert CONFIG_DEFAULTS["caption_max_chars"] == 300
    assert CONFIG_DEFAULTS["screen_title_words_max"] == 6


# --------------------------------------------------------------------------
# screen_title (SPEC-6127, format letterbox) : mots, emoji unique
# --------------------------------------------------------------------------


def test_screen_title_valid_answer_is_kept(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))

    fake, _ = run(workspace, make_config(tmp_path), [answer(screen_title="Attention arnaque totale \U0001F525")])

    assert len(fake.calls) == 1
    assert by_id(read_captions(workspace), "00")["screen_title"] == "Attention arnaque totale \U0001F525"


def test_screen_title_without_an_emoji_is_sent_back_for_correction_then_fails(workspace, tmp_path):
    from clipper.captions import run as run_captions

    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    fake = FakeBackend([answer(screen_title="Sans emoji ici")] * 2)

    with llm.use_backend(fake), pytest.raises(llm.SchemaError, match="exactement un emoji"):
        run_captions(VIDEO_ID, workspace, config=make_config(tmp_path))

    assert len(fake.calls) == 2
    assert "exactement un emoji" in fake.calls[1].prompt
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_screen_title_with_two_emojis_is_a_failure(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    two_emojis = "Choc total \U0001F525\U0001F389"

    with pytest.raises(llm.SchemaError, match="exactement un emoji"):
        run(workspace, make_config(tmp_path), [answer(screen_title=two_emojis)] * 2)
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_screen_title_with_seven_words_is_a_failure(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    seven_words = "un deux trois quatre cinq six sept \U0001F525"

    with pytest.raises(llm.SchemaError, match="7 mots"):
        run(workspace, make_config(tmp_path), [answer(screen_title=seven_words)] * 2)
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_screen_title_emoji_followed_by_variation_selector_is_accepted(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    emoji_vs16 = "Depart imminent \U0001F680️"

    run(workspace, make_config(tmp_path), [answer(screen_title=emoji_vs16)])

    assert by_id(read_captions(workspace), "00")["screen_title"] == emoji_vs16


def test_screen_title_emoji_with_skin_tone_modifier_is_accepted(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    emoji_skin_tone = "Bien joue \U0001F44D\U0001F3FD"

    run(workspace, make_config(tmp_path), [answer(screen_title=emoji_skin_tone)])

    assert by_id(read_captions(workspace), "00")["screen_title"] == emoji_skin_tone


def test_screen_title_zwj_sequence_is_refused(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    zwj_family = "En famille " + "\U0001F468‍\U0001F469‍\U0001F467"

    with pytest.raises(llm.SchemaError, match="ZWJ"):
        run(workspace, make_config(tmp_path), [answer(screen_title=zwj_family)] * 2)
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_screen_title_flag_is_refused(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    flag = "Exclusif France " + "\U0001F1EB\U0001F1F7"

    with pytest.raises(llm.SchemaError, match="drapeau"):
        run(workspace, make_config(tmp_path), [answer(screen_title=flag)] * 2)
    assert not (workspace / VIDEO_ID / "captions.json").exists()


def test_screen_title_words_max_is_configurable(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))
    three_words = "un deux trois \U0001F525"

    with pytest.raises(llm.SchemaError, match="2 au plus"):
        run(workspace, make_config(tmp_path, screen_title_words_max=2), [answer(screen_title=three_words)] * 2)


# --------------------------------------------------------------------------
# screen_title unique par moment multipart (TASK-4078, SPEC-6127)
# --------------------------------------------------------------------------


def test_multipart_screen_title_is_requested_only_once_and_shared_across_parts(workspace, tmp_path):
    write_moments(workspace, moment(0, justification="histoire en 3 actes"))
    write_parts(
        workspace,
        parts_record(0, "multipart", 3, [
            part(1, 0.0, 1.0), part(2, 5.0, 6.0), part(3, 7.0, 8.0),
        ]),
    )

    fake, _ = run(
        workspace, make_config(tmp_path),
        [
            answer(title="Grosse histoire", screen_title="Info choc \U0001F525"),
            answer(include_title=False, include_screen_title=False),
            answer(include_title=False, include_screen_title=False),
        ],
    )

    data = read_captions(workspace)
    assert [c["screen_title"] for c in data["clips"]] == ["Info choc \U0001F525"] * 3
    assert len(fake.calls) == 3


def test_multipart_only_the_first_calls_schema_requires_screen_title(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(
        workspace,
        parts_record(0, "multipart", 3, [
            part(1, 0.0, 1.0), part(2, 5.0, 6.0), part(3, 7.0, 8.0),
        ]),
    )

    fake, _ = run(
        workspace, make_config(tmp_path),
        [
            answer(screen_title="Info choc \U0001F525"),
            answer(include_title=False, include_screen_title=False),
            answer(include_title=False, include_screen_title=False),
        ],
    )

    assert "screen_title" in fake.calls[0].schema["properties"]
    assert "screen_title" in fake.calls[0].schema["required"]
    assert "screen_title" not in fake.calls[1].schema["properties"]
    assert "screen_title" not in fake.calls[1].schema["required"]
    assert "screen_title" not in fake.calls[2].schema["properties"]
    assert "screen_title" not in fake.calls[2].schema["required"]


def test_multipart_later_parts_prompt_cites_the_chosen_screen_title_as_context(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(
        workspace,
        parts_record(0, "multipart", 2, [part(1, 0.0, 1.0), part(2, 5.0, 6.0)]),
    )

    fake, _ = run(
        workspace, make_config(tmp_path),
        [
            answer(screen_title="Info choc \U0001F525"),
            answer(include_title=False, include_screen_title=False),
        ],
    )

    assert "Info choc \U0001F525" in fake.calls[1].prompt


def test_multipart_first_part_failing_writes_nothing(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(
        workspace,
        parts_record(0, "multipart", 2, [part(1, 0.0, 1.0), part(2, 5.0, 6.0)]),
    )

    with pytest.raises(llm.TransientLLMError):
        run(workspace, make_config(tmp_path), [llm.TransientLLMError("quota"), answer()])
    assert not (workspace / VIDEO_ID / "captions.json").exists()


# --------------------------------------------------------------------------
# title unique par moment multipart, suffixe " (Partie N)" (TASK-cb3a)
# --------------------------------------------------------------------------


def test_multipart_title_is_requested_once_and_every_part_gets_the_suffix(workspace, tmp_path):
    write_moments(workspace, moment(0, justification="histoire en 3 actes"))
    write_parts(
        workspace,
        parts_record(0, "multipart", 3, [
            part(1, 0.0, 1.0), part(2, 5.0, 6.0), part(3, 7.0, 8.0),
        ]),
    )

    fake, _ = run(
        workspace, make_config(tmp_path),
        [
            answer(title="Grosse histoire"),
            answer(include_title=False, include_screen_title=False),
            answer(include_title=False, include_screen_title=False),
        ],
    )

    data = read_captions(workspace)
    assert [c["title"] for c in data["clips"]] == [
        "Grosse histoire (Partie 1)", "Grosse histoire (Partie 2)", "Grosse histoire (Partie 3)",
    ]
    assert len(fake.calls) == 3


def test_multipart_only_the_first_call_schema_requires_title(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(
        workspace,
        parts_record(0, "multipart", 3, [
            part(1, 0.0, 1.0), part(2, 5.0, 6.0), part(3, 7.0, 8.0),
        ]),
    )

    fake, _ = run(
        workspace, make_config(tmp_path),
        [
            answer(),
            answer(include_title=False, include_screen_title=False),
            answer(include_title=False, include_screen_title=False),
        ],
    )

    assert "title" in fake.calls[0].schema["properties"]
    assert "title" in fake.calls[0].schema["required"]
    assert "title" not in fake.calls[1].schema["properties"]
    assert "title" not in fake.calls[1].schema["required"]
    assert "title" not in fake.calls[2].schema["properties"]
    assert "title" not in fake.calls[2].schema["required"]


def test_multipart_later_parts_prompt_cites_the_chosen_title_as_context(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(
        workspace,
        parts_record(0, "multipart", 2, [part(1, 0.0, 1.0), part(2, 5.0, 6.0)]),
    )

    fake, _ = run(
        workspace, make_config(tmp_path),
        [
            answer(title="Grosse histoire"),
            answer(include_title=False, include_screen_title=False),
        ],
    )

    assert "Grosse histoire" in fake.calls[1].prompt


def test_single_clip_title_has_no_suffix(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(workspace, parts_record(0, "single", 1, [part(1, 0.0, 3.9)]))

    run(workspace, make_config(tmp_path), [answer(title="Titre unique")])

    assert by_id(read_captions(workspace), "00")["title"] == "Titre unique"


def test_multipart_title_max_chars_requested_accounts_for_the_longest_partie_suffix(workspace, tmp_path):
    write_moments(workspace, moment(0))
    write_parts(
        workspace,
        parts_record(0, "multipart", 3, [
            part(1, 0.0, 1.0), part(2, 5.0, 6.0), part(3, 7.0, 8.0),
        ]),
    )
    base_title = "123456789"  # 9 caracteres ; " (Partie 3)" = 11 -> total 20 = title_max_chars

    fake, _ = run(
        workspace, make_config(tmp_path, title_max_chars=20),
        [
            answer(title=base_title),
            answer(include_title=False, include_screen_title=False),
            answer(include_title=False, include_screen_title=False),
        ],
    )

    assert fake.calls[0].schema["properties"]["title"]["maxLength"] == 9
    data = read_captions(workspace)
    assert data["clips"][0]["title"] == "123456789 (Partie 1)"
    assert all(len(c["title"]) <= 20 for c in data["clips"])
