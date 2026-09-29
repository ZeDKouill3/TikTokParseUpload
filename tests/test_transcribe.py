from __future__ import annotations

import gc
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import wave
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper import llm
from clipper.config import Config
from clipper.gpu import Device
from clipper.llm.fake import FakeBackend

VIDEO_ID = "abcdefghijk"


# --------------------------------------------------------------------------
# Fakes : un WhisperModel factice qui imite faster_whisper (segments rendus
# par un generateur qui garde une reference au modele, comme le vrai).
# --------------------------------------------------------------------------


def _word(word, start, end, probability=0.9):
    return SimpleNamespace(word=word, start=start, end=end, probability=probability)


def _segment(id_, words):
    return SimpleNamespace(
        id=id_,
        start=words[0].start,
        end=words[-1].end,
        text="".join(w.word for w in words),
        words=words,
    )


def default_segments():
    return [
        _segment(1, [_word(" Salut", 0.0, 0.4, 0.95), _word(" Rokstar", 0.4, 0.9, 0.41)]),
        _segment(2, [_word(" GTA", 1.2, 1.5, 0.88), _word(" six", 1.5, 1.9, 0.7), _word(" arrive.", 1.9, 2.5, 0.93)]),
    ]


class FakeHfTokenizer:
    """Imite tokenizers.Tokenizer (attribut hf_tokenizer de WhisperModel) :
    un token par mot et par signe de ponctuation."""

    def encode(self, text, add_special_tokens=True):
        return SimpleNamespace(ids=[hash(t) % 50000 for t in re.findall(r"\w+|[^\w\s]", text)])


class FakeWhisperModel:
    def __init__(self, name, device, compute_type, segments, language="fr"):
        self.name = name
        self.device = device
        self.compute_type = compute_type
        self._segments = segments
        self._language = language
        self.transcribe_calls = []
        self.hf_tokenizer = FakeHfTokenizer()

    def transcribe(self, audio, **kwargs):
        self.transcribe_calls.append((audio, kwargs))
        model = self

        def gen():
            for seg in model._segments:
                yield seg

        info = SimpleNamespace(language=self._language, language_probability=0.97, duration=2.5)
        return gen(), info


class ModelFactory:
    """Records how the model was built and keeps only a weakref to it, so a
    test can tell whether the step released it."""

    def __init__(self, segments=None, language="fr", on_transcribe=None):
        self.segments = segments if segments is not None else default_segments()
        self.language = language
        self.on_transcribe = on_transcribe
        self.built = []  # (name, device, compute_type)
        self.ref = None
        self.audio_seen = None
        self.kwargs_seen = None

    def __call__(self, name, device, compute_type):
        self.built.append((name, device, compute_type))
        model = FakeWhisperModel(name, device, compute_type, self.segments, self.language)
        factory = self
        original = model.transcribe

        def transcribe(audio, **kwargs):
            factory.audio_seen = audio
            factory.kwargs_seen = kwargs
            if factory.on_transcribe is not None:
                factory.on_transcribe(audio)
            return original(audio, **kwargs)

        model.transcribe = transcribe
        self.ref = weakref.ref(model)
        return model

    def alive(self):
        gc.collect()
        return self.ref is not None and self.ref() is not None


def fake_extractor(video_path, audio_path):
    Path(audio_path).write_bytes(b"RIFF fake wav")


def make_config(tmp_path, **transcribe):
    return Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={"transcribe": transcribe} if transcribe else {},
    )


@pytest.fixture
def video_dir(tmp_path):
    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / f"{VIDEO_ID}.mp4").write_bytes(b"fake video")
    meta = {
        "video_id": VIDEO_ID,
        "title": "GTA 6 : tout sur le trailer de Rockstar",
        "description": "On parle de Vice City, Lucia et Jason avec Rockstar Games.",
    }
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


@pytest.fixture
def cpu(monkeypatch):
    import clipper.transcribe as t

    monkeypatch.setattr(t, "get_device", lambda: Device(type="cpu", compute_type="int8"))


VOCAB = {"words": ["Rockstar", "Vice City", "Lucia", "Jason"]}
NO_FIX = {"corrections": []}


def run(tmp_path, factory, config=None, **kwargs):
    from clipper.transcribe import transcribe

    config = config or make_config(tmp_path)
    return transcribe(
        VIDEO_ID,
        tmp_path / "workspace",
        config=config,
        model_factory=factory,
        audio_extractor=kwargs.pop("audio_extractor", fake_extractor),
        **kwargs,
    )


def read_transcript(video_dir):
    return json.loads((video_dir / "transcript.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# C2 : transcript.json, langue, segments, mots
# --------------------------------------------------------------------------


def test_writes_transcript_json_with_language_segments_and_words(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory)

    data = read_transcript(video_dir)
    assert data["language"] == "fr"
    assert [(s["start"], s["end"]) for s in data["segments"]] == [(0.0, 0.9), (1.2, 2.5)]
    assert data["segments"][0]["words"] == [
        {"word": " Salut", "start": 0.0, "end": 0.4, "probability": 0.95},
        {"word": " Rokstar", "start": 0.4, "end": 0.9, "probability": 0.41},
    ]
    assert data["segments"][1]["text"] == " GTA six arrive."
    assert factory.kwargs_seen["word_timestamps"] is True


def test_returns_the_transcript_path(tmp_path, video_dir, cpu):
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        path = run(tmp_path, ModelFactory())
    assert Path(path) == video_dir / "transcript.json"


# --------------------------------------------------------------------------
# C1 : extraction de l'audio (vrai ffmpeg)
# --------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent du PATH")
def test_extracts_16k_mono_wav_with_ffmpeg_and_feeds_it_to_whisper(tmp_path, video_dir, cpu):
    from clipper.transcribe import extract_audio

    video = video_dir / f"{VIDEO_ID}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=1",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=1",
         "-ac", "2", "-shortest", str(video)],
        check=True,
    )
    seen = {}

    def inspect(audio):
        with wave.open(str(audio), "rb") as w:
            seen["channels"] = w.getnchannels()
            seen["rate"] = w.getframerate()
            seen["seconds"] = w.getnframes() / w.getframerate()

    factory = ModelFactory(on_transcribe=inspect)
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory, audio_extractor=extract_audio)

    assert seen["channels"] == 1
    assert seen["rate"] == 16000
    assert 0.9 <= seen["seconds"] <= 1.1


def test_missing_video_is_an_error(tmp_path, video_dir, cpu):
    from clipper.transcribe import TranscribeError

    (video_dir / f"{VIDEO_ID}.mp4").unlink()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])), pytest.raises(TranscribeError):
        run(tmp_path, ModelFactory())


# --------------------------------------------------------------------------
# C3 : modele depuis la config, device depuis clipper.gpu
# --------------------------------------------------------------------------


def test_model_name_from_config_and_device_from_gpu(tmp_path, video_dir, monkeypatch):
    import clipper.transcribe as t

    monkeypatch.setattr(t, "get_device", lambda: Device(type="cuda", compute_type="float16"))
    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory, config=make_config(tmp_path, model="large-v3"))
    assert factory.built == [("large-v3", "cuda", "float16")]


def test_default_model_comes_from_config_defaults(tmp_path, video_dir, cpu):
    from clipper.transcribe import CONFIG_DEFAULTS

    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory)
    assert factory.built == [(CONFIG_DEFAULTS["model"], "cpu", "int8")]


def test_whisper_options_come_from_config(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory, config=make_config(tmp_path, language="fr", beam_size=2, vad_filter=False))
    assert factory.kwargs_seen["language"] == "fr"
    assert factory.kwargs_seen["beam_size"] == 2
    assert factory.kwargs_seen["vad_filter"] is False


# --------------------------------------------------------------------------
# C4 : le modele est libere en fin d'etape (et avant l'appel LLM de correction,
# qui peut etre un LLM local : jamais deux modeles lourds a la fois)
# --------------------------------------------------------------------------


def test_model_released_after_the_step(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory)
    assert not factory.alive()


def test_model_released_before_transcript_fix_call(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    alive_during_fix = []

    def fix(request):
        alive_during_fix.append(factory.alive())
        return NO_FIX

    with llm.use_backend(FakeBackend([VOCAB, fix])):
        run(tmp_path, factory)
    assert alive_during_fix == [False]


def test_model_released_when_transcription_fails(tmp_path, video_dir, cpu):
    def boom(audio):
        raise RuntimeError("whisper a plante")

    factory = ModelFactory(on_transcribe=boom)
    with llm.use_backend(FakeBackend([VOCAB])), pytest.raises(RuntimeError):
        run(tmp_path, factory)
    assert not factory.alive()


# --------------------------------------------------------------------------
# C5 : vocabulaire demande a clipper.llm (usage vocab) depuis titre et
# description, passe en initial_prompt seulement (plus de hotwords, TASK-913b)
# --------------------------------------------------------------------------


def test_vocab_asked_from_title_and_description_and_passed_to_whisper(tmp_path, video_dir, cpu):
    fake = FakeBackend([VOCAB, NO_FIX])
    factory = ModelFactory()
    with llm.use_backend(fake):
        run(tmp_path, factory)

    vocab_call = fake.calls[0]
    assert vocab_call.usage == "vocab"
    assert "GTA 6 : tout sur le trailer de Rockstar" in vocab_call.prompt
    assert "On parle de Vice City, Lucia et Jason avec Rockstar Games." in vocab_call.prompt
    assert vocab_call.images == []
    for name in ("Rockstar", "Vice City", "Lucia", "Jason"):
        assert name in factory.kwargs_seen["initial_prompt"]
    assert "hotwords" not in factory.kwargs_seen
    assert read_transcript(video_dir)["vocab"] == ["Rockstar", "Vice City", "Lucia", "Jason"]


def test_vocab_asked_before_the_model_is_loaded(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    built_at_vocab = []

    def vocab(request):
        built_at_vocab.append(len(factory.built))
        return VOCAB

    with llm.use_backend(FakeBackend([vocab, NO_FIX])):
        run(tmp_path, factory)
    assert built_at_vocab == [0]


def test_invalid_vocab_answer_is_a_failure_and_writes_nothing(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    with llm.use_backend(FakeBackend([{"mots": "pas le bon schema"}])), pytest.raises(llm.SchemaError):
        run(tmp_path, factory)
    assert not (video_dir / "transcript.json").exists()
    assert factory.built == []


def test_vocab_disabled_explicitly_in_config_skips_the_call(tmp_path, video_dir, cpu):
    fake = FakeBackend([NO_FIX])
    factory = ModelFactory()
    with llm.use_backend(fake):
        run(tmp_path, factory, config=make_config(tmp_path, vocab=False))
    assert [c.usage for c in fake.calls] == ["transcript_fix"]
    assert "initial_prompt" not in factory.kwargs_seen
    assert "hotwords" not in factory.kwargs_seen


# --------------------------------------------------------------------------
# TASK-b20f : le prompt passe a whisper ne depasse jamais la fenetre du
# decodeur (448 positions), quelle que soit la taille du vocabulaire. Avant
# le retrait de hotwords (TASK-913b), un vocabulaire long donnait 1 (sot_prev)
# + 223 (hotwords tronques) + 223 (initial_prompt tronque) + 3 (sot_sequence)
# = 450 > 448, RuntimeError "No position encodings are defined for positions
# >= 448" ; sans hotwords, seul initial_prompt occupe encore ce budget.
# --------------------------------------------------------------------------

WHISPER_POSITIONS = 448


def whisper_prompt_length(previous_tokens):
    """Longueur du prompt que faster-whisper 1.2.1 (WhisperModel.get_prompt)
    construit pour une fenetre : [sot_prev] + previous_tokens (223 derniers,
    initial_prompt pour la premiere fenetre puis texte deja transcrit) +
    sot_sequence (sot, langue, tache)."""
    half = WHISPER_POSITIONS // 2
    length = 0
    if previous_tokens:
        length += 1
        length += min(previous_tokens, half - 1)
    return length + 3


class WindowCheckingFactory(ModelFactory):
    """Modele factice qui echoue comme le vrai decodeur Whisper quand le
    prompt d'une fenetre ne laisse plus de position pour generer : premiere
    fenetre conditionnee par initial_prompt, suivantes par le texte deja
    transcrit (223 tokens sur une longue video)."""

    def __call__(self, name, device, compute_type):
        model = super().__call__(name, device, compute_type)
        inner = model.transcribe
        factory = self

        def transcribe(audio, **kwargs):
            initial = kwargs.get("initial_prompt")
            first = len(FakeHfTokenizer().encode(" " + initial.strip()).ids) if initial else 0
            factory.prompt_lengths = [
                whisper_prompt_length(first),
                whisper_prompt_length(WHISPER_POSITIONS // 2 - 1),
            ]
            for length in factory.prompt_lengths:
                if length >= WHISPER_POSITIONS:
                    raise RuntimeError(
                        "No position encodings are defined for positions >= 448, "
                        f"but got position {WHISPER_POSITIONS}"
                    )
            return inner(audio, **kwargs)

        model.transcribe = transcribe
        return model


def credits_vocab(n):
    """Un vocabulaire comme celui d'ivl0nxa3C7o : n noms propres de credits."""
    return {"words": [f"Prenom{i} NOM{i}-COMPOSE{i}" for i in range(n)]}


def test_long_vocab_never_overflows_the_whisper_decoder_window(tmp_path, video_dir, cpu):
    factory = WindowCheckingFactory()
    with llm.use_backend(FakeBackend([credits_vocab(58), NO_FIX])):
        run(tmp_path, factory)
    assert read_transcript(video_dir)["segments"]


@pytest.mark.parametrize("n", [0, 1, 20, 58, 100])
def test_prompt_fits_the_window_with_room_to_generate_whatever_the_vocab_size(tmp_path, video_dir, cpu, n):
    from clipper.transcribe import CONFIG_DEFAULTS

    factory = WindowCheckingFactory()
    with llm.use_backend(FakeBackend([credits_vocab(n), NO_FIX])):
        run(tmp_path, factory)
    tokenizer = FakeHfTokenizer()
    text = factory.kwargs_seen.get("initial_prompt") or ""
    assert len(tokenizer.encode(" " + text.strip()).ids) <= CONFIG_DEFAULTS["vocab_max_tokens"]
    assert "hotwords" not in factory.kwargs_seen
    # au moins une centaine de positions restent pour la transcription
    assert max(factory.prompt_lengths) <= WHISPER_POSITIONS - 100


def test_vocab_max_tokens_comes_from_config(tmp_path, video_dir, cpu):
    factory = WindowCheckingFactory()
    with llm.use_backend(FakeBackend([credits_vocab(58), NO_FIX])):
        run(tmp_path, factory, config=make_config(tmp_path, vocab_max_tokens=10))
    initial_prompt = factory.kwargs_seen["initial_prompt"]
    assert len(FakeHfTokenizer().encode(" " + initial_prompt).ids) <= 10
    assert initial_prompt == "Prenom0 NOM0-COMPOSE0, Prenom1 NOM1-COMPOSE1"
    assert "hotwords" not in factory.kwargs_seen


def test_shortened_vocab_is_logged_with_the_dropped_entries(tmp_path, video_dir, cpu, caplog):
    factory = WindowCheckingFactory()
    with caplog.at_level(logging.WARNING, logger="clipper.transcribe"):
        with llm.use_backend(FakeBackend([credits_vocab(58), NO_FIX])):
            run(tmp_path, factory, config=make_config(tmp_path, vocab_max_tokens=10))
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0]
    assert "vocab_max_tokens" in message and "10" in message
    # les entrees ecartees sont nommees
    assert "Prenom2 NOM2-COMPOSE2" in message and "Prenom57 NOM57-COMPOSE57" in message


def test_short_vocab_is_passed_whole_without_warning(tmp_path, video_dir, cpu, caplog):
    factory = WindowCheckingFactory()
    with caplog.at_level(logging.WARNING, logger="clipper.transcribe"):
        with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
            run(tmp_path, factory)
    assert factory.kwargs_seen["initial_prompt"] == "Rockstar, Vice City, Lucia, Jason"
    assert "hotwords" not in factory.kwargs_seen
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_model_without_tokenizer_bounds_the_prompt_by_utf8_bytes_and_says_so(
    tmp_path, video_dir, cpu, caplog
):
    """Whisper tokenise en BPE sur les octets : un token couvre au moins un
    octet, donc le nombre d'octets UTF-8 majore le nombre de tokens. Un
    modele qui n'expose pas hf_tokenizer reste borne, et c'est journalise."""
    class NoTokenizerFactory(WindowCheckingFactory):
        def __call__(self, name, device, compute_type):
            model = super().__call__(name, device, compute_type)
            del model.hf_tokenizer
            return model

    factory = NoTokenizerFactory()
    with caplog.at_level(logging.WARNING, logger="clipper.transcribe"):
        with llm.use_backend(FakeBackend([{"words": ["Éric", "Zoé Lefèvre", "Anaïs"]}, NO_FIX])):
            run(tmp_path, factory, config=make_config(tmp_path, vocab_max_tokens=18))
    # " Éric, Zoé Lefèvre" = 21 octets > 18 ; " Éric Zoé Lefèvre" = 20 > 18
    assert factory.kwargs_seen["initial_prompt"] == "Éric"
    assert "hotwords" not in factory.kwargs_seen
    messages = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "hf_tokenizer" in messages
    assert "Zoé Lefèvre" in messages and "Anaïs" in messages


def test_full_vocab_is_kept_in_transcript_and_for_the_correction(tmp_path, video_dir, cpu):
    """Seul le prompt de whisper est borne : la correction par clipper.llm et
    transcript.json gardent tout le vocabulaire."""
    vocab = credits_vocab(58)
    fake = FakeBackend([vocab, NO_FIX])
    with llm.use_backend(fake):
        run(tmp_path, WindowCheckingFactory())
    assert read_transcript(video_dir)["vocab"] == vocab["words"]
    assert "Prenom57 NOM57-COMPOSE57" in fake.calls[1].prompt


@pytest.mark.parametrize("bound", [0, 121, 400])
def test_vocab_max_tokens_outside_the_window_is_refused_before_loading_the_model(
    tmp_path, video_dir, cpu, bound
):
    from clipper.transcribe import TranscribeError

    factory = WindowCheckingFactory()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])), pytest.raises(TranscribeError, match="vocab_max_tokens"):
        run(tmp_path, factory, config=make_config(tmp_path, vocab_max_tokens=bound))
    assert factory.built == []
    assert not (video_dir / "transcript.json").exists()


# --------------------------------------------------------------------------
# C6 : correction (usage transcript_fix) : texte des mots seulement
# --------------------------------------------------------------------------


def test_fix_changes_word_text_only(tmp_path, video_dir, cpu):
    fake = FakeBackend([
        VOCAB,
        {"corrections": [
            {"i": 1, "old": "Rokstar", "word": "Rockstar"},
            {"i": 3, "old": "six", "word": "6"},
        ]},
    ])
    with llm.use_backend(fake):
        run(tmp_path, ModelFactory())

    fix_call = fake.calls[1]
    assert fix_call.usage == "transcript_fix"
    assert "Rokstar" in fix_call.prompt
    assert "Vice City" in fix_call.prompt  # le vocabulaire guide la correction

    data = read_transcript(video_dir)
    assert data["segments"] == [
        {
            "id": 1, "start": 0.0, "end": 0.9, "text": " Salut Rockstar",
            "words": [
                {"word": " Salut", "start": 0.0, "end": 0.4, "probability": 0.95},
                {"word": " Rockstar", "start": 0.4, "end": 0.9, "probability": 0.41},
            ],
        },
        {
            "id": 2, "start": 1.2, "end": 2.5, "text": " GTA 6 arrive.",
            "words": [
                {"word": " GTA", "start": 1.2, "end": 1.5, "probability": 0.88},
                {"word": " 6", "start": 1.5, "end": 1.9, "probability": 0.7},
                {"word": " arrive.", "start": 1.9, "end": 2.5, "probability": 0.93},
            ],
        },
    ]


def test_fix_cannot_change_timecodes_or_word_count(tmp_path, video_dir, cpu):
    """Une reponse qui tente d'ajouter des champs (timecodes) ou de viser un
    mot inexistant est un echec, pas une donnee."""
    for bad in (
        {"corrections": [{"i": 1, "old": "Rokstar", "word": "Rockstar", "start": 9.9}]},
        {"corrections": [{"i": 5, "old": "en", "word": "en trop"}]},
        {"corrections": [{"i": -1, "old": "avant", "word": "avant"}]},
        {"corrections": [{"i": 1, "word": "Rockstar"}]},  # old manquant
        {"words": [" Salut", " Rockstar", " Games"]},
    ):
        (video_dir / "transcript.json").unlink(missing_ok=True)
        with llm.use_backend(FakeBackend([VOCAB, bad])), pytest.raises(llm.SchemaError):
            run(tmp_path, ModelFactory())
        assert not (video_dir / "transcript.json").exists()


def test_fix_word_that_would_merge_words_is_refused(tmp_path, video_dir, cpu):
    """Un mot corrige ne peut pas contenir d'espace interne : sinon il
    deviendrait deux mots pour les sous-titres sans timecode propre."""
    bad = {"corrections": [{"i": 0, "old": "Salut", "word": "Salut les"}]}
    with llm.use_backend(FakeBackend([VOCAB, bad])):
        with pytest.raises(llm.SchemaError):
            run(tmp_path, ModelFactory())
    assert not (video_dir / "transcript.json").exists()


def test_fix_correction_whose_old_does_not_match_the_actual_word_is_refused_and_logged(
    tmp_path, video_dir, cpu
):
    """Une correction visant un mot different de celui reellement present a
    cet index (LLM decale, index hallucine...) ne correspond pas au texte :
    refusee, jamais appliquee en silence (ADR-ad2e), et journalisee dans
    llm_refusals.jsonl (meme convention que captions.py)."""
    bad = {"corrections": [{"i": 1, "old": "Rockstar", "word": "Rockstars"}]}  # le mot 1 est " Rokstar"
    with llm.use_backend(FakeBackend([VOCAB, bad])):
        with pytest.raises(llm.SchemaError):
            run(tmp_path, ModelFactory())
    assert not (video_dir / "transcript.json").exists()

    refusals_path = video_dir / "llm_refusals.jsonl"
    assert refusals_path.exists()
    entries = [json.loads(line) for line in refusals_path.read_text(encoding="utf-8").splitlines()]
    assert any(
        e["usage"] == "transcript_fix" and "Rokstar" in e["error"] and "Rockstar" in e["error"]
        for e in entries
    )


def test_fix_disabled_explicitly_in_config_skips_the_call(tmp_path, video_dir, cpu):
    fake = FakeBackend([VOCAB])
    with llm.use_backend(fake):
        run(tmp_path, ModelFactory(), config=make_config(tmp_path, transcript_fix=False))
    assert [c.usage for c in fake.calls] == ["vocab"]
    assert read_transcript(video_dir)["segments"][0]["words"][1]["word"] == " Rokstar"


# --------------------------------------------------------------------------
# C7 : correction par tranches sur les longues videos
# --------------------------------------------------------------------------


def test_fix_runs_in_chunks_with_global_word_indexes_mapped_per_chunk(tmp_path, video_dir, cpu):
    segments = [
        _segment(i, [_word(f" mot{i}a", i * 1.0, i * 1.0 + 0.4), _word(f" mot{i}b", i * 1.0 + 0.4, i * 1.0 + 0.9)])
        for i in range(5)
    ]  # 10 mots, 2 par segment
    answers = [
        {"corrections": [{"i": 0, "old": "mot0a", "word": "UN"}]},     # tranche 1 : mots 0-3
        {"corrections": [{"i": 1, "old": "mot2b", "word": "DEUX"}]},   # tranche 2 : mots 4-7 -> mot 5
        {"corrections": [{"i": 1, "old": "mot4b", "word": "TROIS"}]},  # tranche 3 : mots 8-9 -> mot 9
    ]
    fake = FakeBackend([VOCAB, *answers])
    with llm.use_backend(fake):
        run(tmp_path, ModelFactory(segments=segments), config=make_config(tmp_path, fix_chunk_words=4))

    assert [c.usage for c in fake.calls] == ["vocab"] + ["transcript_fix"] * 3
    words = [w["word"] for s in read_transcript(video_dir)["segments"] for w in s["words"]]
    assert words == [" UN", " mot0b", " mot1a", " mot1b", " mot2a", " DEUX", " mot3a", " mot3b", " mot4a", " TROIS"]
    # une tranche ne coupe jamais un segment
    assert "mot2a" in fake.calls[2].prompt and "mot2b" in fake.calls[2].prompt
    assert "mot2a" not in fake.calls[1].prompt


def test_transient_llm_error_during_fix_propagates_without_writing(tmp_path, video_dir, cpu):
    with llm.use_backend(FakeBackend([VOCAB, llm.TransientLLMError("quota")])):
        with pytest.raises(llm.TransientLLMError):
            run(tmp_path, ModelFactory())
    assert not (video_dir / "transcript.json").exists()


# --------------------------------------------------------------------------
# C12 : tranches de correction traitees en parallele (fix_parallel)
# --------------------------------------------------------------------------


def _many_word_segments(n):
    return [
        _segment(i, [_word(f" mot{i}", i * 1.0, i * 1.0 + 0.4)])
        for i in range(n)
    ]


class ConcurrencyTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def response(self, request):
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        time.sleep(0.05)
        with self.lock:
            self.current -= 1
        return {"corrections": []}


def test_fix_chunks_run_concurrently_up_to_fix_parallel(tmp_path, video_dir, cpu):
    segments = _many_word_segments(12)  # fix_chunk_words=2 -> 6 tranches
    tracker = ConcurrencyTracker()
    fake = FakeBackend([VOCAB] + [tracker.response] * 6)
    with llm.use_backend(fake):
        run(
            tmp_path,
            ModelFactory(segments=segments),
            config=make_config(tmp_path, fix_chunk_words=2, fix_parallel=3),
        )
    assert tracker.peak == 3


def test_fix_parallel_defaults_to_config_value_of_four(tmp_path, video_dir, cpu):
    segments = _many_word_segments(16)  # fix_chunk_words=2 -> 8 tranches
    tracker = ConcurrencyTracker()
    fake = FakeBackend([VOCAB] + [tracker.response] * 8)
    with llm.use_backend(fake):
        run(
            tmp_path,
            ModelFactory(segments=segments),
            config=make_config(tmp_path, fix_chunk_words=2),
        )
    assert tracker.peak == 4


def test_fix_parallel_result_matches_sequential_processing_regardless_of_scheduling(
    tmp_path, video_dir, cpu
):
    """Chaque tranche est corrigee d'apres son propre contenu (pas d'apres
    l'ordre d'arrivee des reponses scriptees) : le resultat final est le
    meme que le traitement sequentiel, quel que soit l'ordre d'execution des
    threads."""
    segments = _many_word_segments(10)  # fix_chunk_words=2 -> 5 tranches

    def make_fix(chunk_index):
        def respond(request):
            time.sleep(0.01 * (5 - chunk_index))  # ordre d'arrivee inverse
            assert f"mot{chunk_index * 2}" in request.prompt
            return {"corrections": [{"i": 0, "old": f"mot{chunk_index * 2}", "word": f"CORRIGE{chunk_index}"}]}

        return respond

    fake = FakeBackend([VOCAB, *(make_fix(i) for i in range(5))])
    with llm.use_backend(fake):
        run(
            tmp_path,
            ModelFactory(segments=segments),
            config=make_config(tmp_path, fix_chunk_words=2, fix_parallel=5),
        )

    words = [w["word"] for s in read_transcript(video_dir)["segments"] for w in s["words"]]
    assert words == [
        " CORRIGE0", " mot1",
        " CORRIGE1", " mot3",
        " CORRIGE2", " mot5",
        " CORRIGE3", " mot7",
        " CORRIGE4", " mot9",
    ]


def test_one_chunk_failure_fails_the_step_with_its_reason_others_may_run(
    tmp_path, video_dir, cpu
):
    from clipper.transcribe import TranscribeError

    segments = _many_word_segments(8)  # fix_chunk_words=2 -> 4 tranches

    def boom(request):
        raise TranscribeError("tranche corrompue")

    fake = FakeBackend([VOCAB, {"corrections": []}, boom, {"corrections": []}, {"corrections": []}])
    with llm.use_backend(fake):
        with pytest.raises(TranscribeError, match="tranche corrompue"):
            run(
                tmp_path,
                ModelFactory(segments=segments),
                config=make_config(tmp_path, fix_chunk_words=2, fix_parallel=4),
            )
    assert not (video_dir / "transcript.json").exists()


# --------------------------------------------------------------------------
# C13 : transcript_raw.json (resultat brut de whisper) et reprise sans
# relancer whisper apres un echec de la correction
# --------------------------------------------------------------------------


def read_raw(video_dir):
    return json.loads((video_dir / "transcript_raw.json").read_text(encoding="utf-8"))


def test_transcript_raw_json_written_before_correction(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory)

    raw = read_raw(video_dir)
    assert raw["language"] == "fr"
    assert raw["vocab"] == ["Rockstar", "Vice City", "Lucia", "Jason"]
    # le brut garde le mot non corrige, transcript.json aura la correction
    assert raw["segments"][0]["words"][1]["word"] == " Rokstar"


def test_retry_after_fix_failure_reuses_raw_and_does_not_rerun_whisper(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, llm.TransientLLMError("quota")])):
        with pytest.raises(llm.TransientLLMError):
            run(tmp_path, factory)
    assert len(factory.built) == 1
    assert (video_dir / "transcript_raw.json").exists()
    assert not (video_dir / "transcript.json").exists()

    fake_retry = FakeBackend([NO_FIX])
    with llm.use_backend(fake_retry):
        run(tmp_path, factory)

    assert len(factory.built) == 1  # whisper pas relance
    assert [c.usage for c in fake_retry.calls] == ["transcript_fix"]  # vocab pas redemande
    assert read_transcript(video_dir)["language"] == "fr"


def test_retry_reuses_raw_vocab_and_applies_correction(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, llm.TransientLLMError("quota")])):
        with pytest.raises(llm.TransientLLMError):
            run(tmp_path, factory)

    with llm.use_backend(FakeBackend([{"corrections": [{"i": 1, "old": "Rokstar", "word": "Rockstar"}]}])):
        run(tmp_path, factory)

    data = read_transcript(video_dir)
    assert data["vocab"] == ["Rockstar", "Vice City", "Lucia", "Jason"]
    assert data["segments"][0]["words"][1]["word"] == " Rockstar"


def test_force_redoes_whisper_even_if_raw_transcript_exists(tmp_path, video_dir, cpu):
    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory)
    assert len(factory.built) == 1

    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory, force=True)
    assert len(factory.built) == 2


# --------------------------------------------------------------------------
# C9 : cache par video (ADR-b16b)
# --------------------------------------------------------------------------


def test_existing_transcript_is_not_redone_unless_forced(tmp_path, video_dir, cpu):
    (video_dir / "transcript.json").write_text('{"language": "en", "segments": []}', encoding="utf-8")
    factory = ModelFactory()
    fake = FakeBackend([])
    with llm.use_backend(fake):
        path = run(tmp_path, factory)
    assert Path(path) == video_dir / "transcript.json"
    assert factory.built == [] and fake.calls == []

    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory, force=True)
    assert read_transcript(video_dir)["language"] == "fr"


def test_default_fix_chunk_words_and_fix_parallel(tmp_path):
    from clipper.transcribe import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS["fix_chunk_words"] == 3000
    assert CONFIG_DEFAULTS["fix_parallel"] == 4


def test_config_section_is_accepted_by_clipper_config(tmp_path):
    from clipper.config import load_config

    (tmp_path / "config.toml").write_text('[transcribe]\nmodel = "tiny"\nvocab = false\n', encoding="utf-8")
    section = load_config(tmp_path / "config.toml").section("transcribe")
    assert section["model"] == "tiny"
    assert section["vocab"] is False
    assert section["transcript_fix"] is True


# --------------------------------------------------------------------------
# C11 : DLL cuBLAS/cuDNN des paquets pip nvidia rendues trouvables avant de
# charger faster-whisper quand le device est cuda sous Windows (TASK-f6c8) :
# ajouter les dossiers bin au PATH du processus, jamais os.add_dll_directory
# (mesure sur materiel reel : add_dll_directory seul ne suffit pas, voir le
# journal de la tache).
# --------------------------------------------------------------------------


@pytest.fixture
def fake_nvidia_bin_dirs(tmp_path):
    """Simule l'arborescence site-packages/nvidia/*/bin de nvidia-cublas-cu12
    et nvidia-cudnn-cu12, sans les vraies DLL ni le vrai GPU."""
    nvidia_dir = tmp_path / "site-packages" / "nvidia"
    cublas_bin = nvidia_dir / "cublas" / "bin"
    cudnn_bin = nvidia_dir / "cudnn" / "bin"
    cublas_bin.mkdir(parents=True)
    cudnn_bin.mkdir(parents=True)
    return nvidia_dir, [cublas_bin, cudnn_bin]


def _fake_find_spec(nvidia_dir):
    def find_spec(name):
        if name != "nvidia":
            return None
        return SimpleNamespace(submodule_search_locations=[str(nvidia_dir)])

    return find_spec


def test_cuda_dll_dirs_are_prefixed_on_path_before_loading_model_on_windows(
    tmp_path, video_dir, monkeypatch, fake_nvidia_bin_dirs
):
    import clipper.transcribe as t

    nvidia_dir, bin_dirs = fake_nvidia_bin_dirs
    monkeypatch.setattr(t.sys, "platform", "win32")
    # ";" (pas le ":" reel de l'hote) : sur Windows os.pathsep est ";", or
    # "C:\Windows\System32" contient deja un ":" (lettre de lecteur) que ":"
    # couperait a tort.
    monkeypatch.setattr(t.os, "pathsep", ";")
    monkeypatch.setattr(t, "get_device", lambda: Device(type="cuda", compute_type="float16"))
    monkeypatch.setattr(t, "find_spec", _fake_find_spec(nvidia_dir))
    monkeypatch.setenv("PATH", r"C:\Windows\System32")

    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, ModelFactory())

    path_parts = os.environ["PATH"].split(os.pathsep)
    assert str(bin_dirs[0]) in path_parts
    assert str(bin_dirs[1]) in path_parts
    assert path_parts.index(str(bin_dirs[0])) < path_parts.index(r"C:\Windows\System32")


def test_cuda_dll_dirs_untouched_when_device_is_cpu(
    tmp_path, video_dir, monkeypatch, fake_nvidia_bin_dirs, cpu
):
    import clipper.transcribe as t

    nvidia_dir, bin_dirs = fake_nvidia_bin_dirs
    monkeypatch.setattr(t.sys, "platform", "win32")
    monkeypatch.setattr(t, "find_spec", _fake_find_spec(nvidia_dir))
    monkeypatch.setenv("PATH", r"C:\Windows\System32")

    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, ModelFactory())

    assert os.environ["PATH"] == r"C:\Windows\System32"


def test_cuda_dll_dirs_untouched_on_non_windows_platform(
    tmp_path, video_dir, monkeypatch, fake_nvidia_bin_dirs
):
    import clipper.transcribe as t

    nvidia_dir, bin_dirs = fake_nvidia_bin_dirs
    monkeypatch.setattr(t.sys, "platform", "linux")
    monkeypatch.setattr(t, "get_device", lambda: Device(type="cuda", compute_type="float16"))
    monkeypatch.setattr(t, "find_spec", _fake_find_spec(nvidia_dir))
    monkeypatch.setenv("PATH", "/usr/bin")

    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, ModelFactory())

    assert os.environ["PATH"] == "/usr/bin"


def test_missing_nvidia_packages_leaves_path_and_device_untouched(
    tmp_path, video_dir, monkeypatch
):
    """Paquets nvidia absents (find_spec renvoie None) : pas de repli
    silencieux vers le CPU, le device cuda est toujours transmis tel quel."""
    import clipper.transcribe as t

    monkeypatch.setattr(t.sys, "platform", "win32")
    monkeypatch.setattr(t, "get_device", lambda: Device(type="cuda", compute_type="float16"))
    monkeypatch.setattr(t, "find_spec", lambda name: None)
    monkeypatch.setenv("PATH", r"C:\Windows\System32")

    factory = ModelFactory()
    with llm.use_backend(FakeBackend([VOCAB, NO_FIX])):
        run(tmp_path, factory)

    assert os.environ["PATH"] == r"C:\Windows\System32"
    assert factory.built == [("small", "cuda", "float16")]


# --------------------------------------------------------------------------
# C10 : integration optionnelle avec le vrai faster-whisper, modele tiny
# (telecharge au premier lancement) : CLIPPER_WHISPER_INTEGRATION=1 pytest
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CLIPPER_WHISPER_INTEGRATION") != "1",
    reason="integration whisper : definir CLIPPER_WHISPER_INTEGRATION=1 (telecharge le modele tiny)",
)
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent du PATH")
def test_integration_tiny_model_transcribes_a_short_clip(tmp_path, video_dir):
    """Transcrit CLIPPER_WHISPER_CLIP (un court extrait parle) s'il est
    fourni, sinon quelques secondes generees par ffmpeg."""
    from clipper.transcribe import transcribe

    video = video_dir / f"{VIDEO_ID}.mp4"
    clip = os.environ.get("CLIPPER_WHISPER_CLIP")
    if clip:
        shutil.copyfile(clip, video)
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=3",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
             "-shortest", str(video)],
            check=True,
        )
    config = make_config(tmp_path, model="tiny", vocab=False, transcript_fix=False)
    transcribe(VIDEO_ID, tmp_path / "workspace", config=config)

    data = read_transcript(video_dir)
    assert isinstance(data["language"], str) and data["language"]
    for seg in data["segments"]:
        assert seg["start"] <= seg["end"]
        for w in seg["words"]:
            assert set(w) == {"word", "start", "end", "probability"}
    if clip:
        assert any(seg["words"] for seg in data["segments"])
