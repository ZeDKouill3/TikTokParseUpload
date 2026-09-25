from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from clipper import llm
from clipper.config import Config
from clipper.llm.fake import FakeBackend
from clipper.subtitles import CONFIG_DEFAULTS

VIDEO_ID = "abcdefghijk"
CLIP_ID = "03"


def _word(word, start, end):
    return {"word": word, "start": start, "end": end, "probability": 0.9}


def default_words():
    # 8 mots, 0.0 -> 4.6s ; couvre l'intervalle [1.0, 4.0]
    return [
        _word(" Salut", 0.0, 0.4),
        _word(" tout", 0.5, 0.8),
        _word(" le", 0.8, 1.0),
        _word(" monde", 1.1, 1.6),
        _word(" bienvenue", 1.7, 2.3),
        _word(" sur", 2.4, 2.6),
        _word(" GTA", 2.7, 3.2),
        _word(" six.", 3.3, 4.6),
    ]


def make_transcript(words=None):
    return {
        "video_id": VIDEO_ID,
        "language": "fr",
        "segments": [{"id": 1, "start": words[0]["start"] if words else 0.0,
                      "end": words[-1]["end"] if words else 0.0,
                      "text": "", "words": words if words is not None else default_words()}],
    }


def make_config(tmp_path, **subtitles):
    return Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections={"subtitles": subtitles} if subtitles else {},
    )


@pytest.fixture
def video_dir(tmp_path):
    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / "transcript.json").write_text(json.dumps(make_transcript()), encoding="utf-8")
    return d


def run(tmp_path, config=None, **kwargs):
    from clipper.subtitles import generate

    config = config or make_config(tmp_path)
    return generate(
        VIDEO_ID, CLIP_ID,
        kwargs.pop("start", 1.0), kwargs.pop("end", 4.0),
        tmp_path / "workspace",
        config=config,
        **kwargs,
    )


NO_EMPHASIS = {"indices": []}


def parse_ass(path: Path) -> dict:
    """Minimal .ass parser: script info, style fields, dialogue events."""
    text = path.read_text(encoding="utf-8")
    info = dict(re.findall(r"^(PlayResX|PlayResY):\s*(\d+)", text, re.MULTILINE))
    style_line = re.search(r"^Format:\s*(.+)\nStyle:\s*(.+)$", text, re.MULTILINE)
    style_fields = [f.strip() for f in style_line.group(1).split(",")]
    style_values = [v.strip() for v in style_line.group(2).split(",")]
    style = dict(zip(style_fields, style_values))
    events = []
    for m in re.finditer(r"^Dialogue:\s*(.+)$", text, re.MULTILINE):
        parts = m.group(1).split(",", 9)
        events.append({
            "layer": parts[0], "start": parts[1], "end": parts[2],
            "style": parts[3], "text": parts[9],
        })
    return {"info": info, "style": style, "events": events, "raw": text}


def to_seconds(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


# --------------------------------------------------------------------------
# C1 : .ass 1080x1920 depuis un intervalle + transcription mot par mot
# --------------------------------------------------------------------------


def test_generates_ass_file_at_1080x1920(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path)
    assert Path(path).exists()
    assert Path(path).suffix == ".ass"
    doc = parse_ass(Path(path))
    assert doc["info"]["PlayResX"] == "1080"
    assert doc["info"]["PlayResY"] == "1920"


def test_returns_the_ass_path(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path)
    assert Path(path) == tmp_path / "workspace" / VIDEO_ID / "subtitles" / f"{CLIP_ID}.ass"


# --------------------------------------------------------------------------
# C2 : groupes de 2 a 4 mots (un evenement Dialogue par groupe)
# --------------------------------------------------------------------------


def test_words_are_grouped_by_2_to_4_words_per_event(tmp_path, video_dir):
    # mots chevauchant [1.0, 4.0] (par > start, fin < end exclus aux bornes) :
    # "monde", "bienvenue", "sur", "GTA", "six." = 5 mots
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path)
    doc = parse_ass(Path(path))
    assert len(doc["events"]) >= 1
    total_words = 0
    for ev in doc["events"]:
        tokens = re.findall(r"\\k\d+(?:\\c[^}]*)?\}([^{]*)", ev["text"])
        n = len([t for t in tokens if t.strip()])
        assert 2 <= n <= 4
        total_words += n
    assert total_words == 5


# --------------------------------------------------------------------------
# C6 : timecodes relatifs au debut du clip (start -> 0)
# --------------------------------------------------------------------------


def test_timecodes_are_relative_to_clip_start(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, start=1.0, end=4.0)
    doc = parse_ass(Path(path))
    first = doc["events"][0]
    # premier mot dans l'intervalle : "monde" a 1.1-1.6
    assert to_seconds(first["start"]) == pytest.approx(1.1 - 1.0, abs=0.011)
    last = doc["events"][-1]
    # dernier mot : "six." a 3.3-4.6
    assert to_seconds(last["end"]) == pytest.approx(4.6 - 1.0, abs=0.011)


# --------------------------------------------------------------------------
# C3 : karaoke, mot courant surligne (tags \k par mot, duree = fin-debut)
# --------------------------------------------------------------------------


def test_each_word_has_a_karaoke_tag_sized_to_its_duration(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path)
    doc = parse_ass(Path(path))
    first_event = doc["events"][0]
    # "monde" 1.1-1.6 (0.5s = 50cs), "bienvenue" 1.7-2.3 (0.6s = 60cs)
    assert "\\k50}" in first_event["text"] and " monde" in first_event["text"]
    assert "\\k60}" in first_event["text"] and " bienvenue" in first_event["text"]


def test_karaoke_style_uses_distinct_primary_and_secondary_colours(tmp_path, video_dir):
    """SecondaryColour (mots pas encore prononces) != PrimaryColour (mot en
    cours / deja prononce) : c'est ce qui fait le surlignage karaoke."""
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path)
    doc = parse_ass(Path(path))
    assert doc["style"]["PrimaryColour"] != doc["style"]["SecondaryColour"]


# --------------------------------------------------------------------------
# C4 : gros texte avec contour (style : Fontsize eleve, Outline > 0)
# --------------------------------------------------------------------------


def test_style_has_large_font_and_outline(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path)
    doc = parse_ass(Path(path))
    assert int(doc["style"]["Fontsize"]) >= 60
    assert float(doc["style"]["Outline"]) > 0


def test_font_size_and_outline_come_from_config(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, config=make_config(tmp_path, font_size=120, outline=8))
    doc = parse_ass(Path(path))
    assert doc["style"]["Fontsize"] == "120"
    assert doc["style"]["Outline"] == "8"


# --------------------------------------------------------------------------
# C5 : mots d'emphase choisis par clipper.llm (usage emphasis), couleur
# distincte de la couleur normale
# --------------------------------------------------------------------------


def test_emphasis_words_asked_to_llm_and_coloured_distinctly(tmp_path, video_dir):
    # mots : 0 monde, 1 bienvenue, 2 sur, 3 GTA, 4 six.
    fake = FakeBackend([{"indices": [3]}])  # "GTA"
    with llm.use_backend(fake):
        path = run(tmp_path)

    call = fake.calls[0]
    assert call.usage == "emphasis"
    for w in ("monde", "bienvenue", "sur", "GTA", "six."):
        assert w in call.prompt

    doc = parse_ass(Path(path))
    emphasis_color = CONFIG_DEFAULTS["emphasis_color"]
    assert any(emphasis_color in ev["text"] and "GTA" in ev["text"] for ev in doc["events"])
    # les autres mots ne portent pas la couleur d'emphase
    assert not any(emphasis_color in ev["text"] and "monde" in ev["text"] for ev in doc["events"])


def test_emphasis_disabled_in_config_skips_the_llm_call(tmp_path, video_dir):
    fake = FakeBackend([])
    with llm.use_backend(fake):
        run(tmp_path, config=make_config(tmp_path, emphasis=False))
    assert fake.calls == []


def test_invalid_emphasis_answer_is_a_failure_and_writes_nothing(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([{"mots": "pas le bon schema"}])), pytest.raises(llm.SchemaError):
        run(tmp_path)
    assert not (tmp_path / "workspace" / VIDEO_ID / "subtitles" / f"{CLIP_ID}.ass").exists()


# --------------------------------------------------------------------------
# C7 : position verticale parametrable pour eviter une zone donnee (visages)
# --------------------------------------------------------------------------


def test_default_position_is_bottom(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path)
    doc = parse_ass(Path(path))
    assert doc["style"]["Alignment"] == "2"  # bas, centre


def test_avoid_zone_over_default_position_moves_subtitles_to_top(tmp_path, video_dir):
    # visage detecte sur le tiers bas de l'image (recouvre la position par defaut)
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, avoid_zone=(0.75, 1.0))
    doc = parse_ass(Path(path))
    assert doc["style"]["Alignment"] == "8"  # haut, centre


def test_avoid_zone_not_overlapping_default_position_keeps_bottom(tmp_path, video_dir):
    # visage en haut de l'image : ne gene pas la position par defaut (bas)
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, avoid_zone=(0.0, 0.2))
    doc = parse_ass(Path(path))
    assert doc["style"]["Alignment"] == "2"


# --------------------------------------------------------------------------
# C9 : rendu ffmpeg d'echantillon, test optionnel (saute par defaut)
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CLIPPER_SUBTITLES_INTEGRATION") != "1",
    reason="integration ffmpeg : definir CLIPPER_SUBTITLES_INTEGRATION=1",
)
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent du PATH")
def test_integration_ffmpeg_burns_the_generated_ass_into_a_sample_clip(tmp_path, video_dir):
    """Le .ass produit est un filtre ``ass=`` ffmpeg valide : brule-le sur un
    court echantillon genere par lavfi et verifie que la sortie existe."""
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        ass_path = run(tmp_path)

    sample = tmp_path / "sample.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=1",
         str(sample)],
        check=True,
    )

    out = tmp_path / "sample_subtitled.mp4"
    # cwd = dossier du .ass : evite les soucis d'echappement du ':' d'une
    # lettre de lecteur Windows dans le filtre ffmpeg.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(sample.resolve()),
         "-vf", f"ass={Path(ass_path).name}", str(out.resolve())],
        cwd=Path(ass_path).parent, check=True,
    )

    assert out.exists() and out.stat().st_size > 0


# --------------------------------------------------------------------------
# Contraintes du depot : cache par resultat existant (ADR-b16b), erreur si
# transcript.json absent
# --------------------------------------------------------------------------


def test_existing_ass_is_not_regenerated_unless_forced(tmp_path, video_dir):
    fake = FakeBackend([NO_EMPHASIS])
    with llm.use_backend(fake):
        path = run(tmp_path)
    original = Path(path).read_text(encoding="utf-8")

    with llm.use_backend(FakeBackend([])):  # aucune reponse scriptee : ne doit pas etre appele
        path2 = run(tmp_path)
    assert Path(path2) == Path(path)
    assert Path(path2).read_text(encoding="utf-8") == original

    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        run(tmp_path, force=True)


def test_missing_transcript_is_an_error(tmp_path, video_dir):
    from clipper.subtitles import SubtitlesError

    (video_dir / "transcript.json").unlink()
    with llm.use_backend(FakeBackend([NO_EMPHASIS])), pytest.raises(SubtitlesError):
        run(tmp_path)


def test_config_section_is_accepted_by_clipper_config(tmp_path):
    from clipper.config import load_config

    (tmp_path / "config.toml").write_text(
        '[subtitles]\nfont_size = 110\nmax_words_per_group = 3\n', encoding="utf-8"
    )
    section = load_config(tmp_path / "config.toml").section("subtitles")
    assert section["font_size"] == 110
    assert section["max_words_per_group"] == 3
    assert section["min_words_per_group"] == 2
