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
            "style": parts[3], "margin_v": parts[7], "text": parts[9],
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
# C7 (TASK-29cf) : position par evenement dans une zone sure TikTok, hors
# visages du plan ou le sous-titre s'affiche, jamais sur l'accroche.
# --------------------------------------------------------------------------

H = 1920
SAFE_TOP, SAFE_BOTTOM = 0.20 * H, 0.78 * H  # zone sure par defaut (px)


def event_bands(doc: dict) -> list[tuple[float, float]]:
    """Bande verticale [haut, bas] (px) occupee par chaque evenement : style
    aligne en bas (Alignment 2), le bas du texte est a PlayResY - MarginV de
    l'evenement, sur une hauteur text_band_height."""
    assert doc["style"]["Alignment"] == "2"
    band = int(CONFIG_DEFAULTS["text_band_height"])
    bands = []
    for ev in doc["events"]:
        margin_v = int(ev["margin_v"]) or int(doc["style"]["MarginV"])
        bottom = H - margin_v
        bands.append((bottom - band, bottom))
    return bands


def overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def px(zone: tuple[float, float]) -> tuple[float, float]:
    return (zone[0] * H, zone[1] * H)


def zones(*entries):
    """[(start, end, [(haut, bas), ...]), ...] -> format avoid_zones."""
    return [{"start": s, "end": e, "bands": [list(b) for b in bands]} for s, e, bands in entries]


def in_lower_third_of_safe_zone(band: tuple[float, float]) -> bool:
    centre = (band[0] + band[1]) / 2
    return centre >= SAFE_TOP + 2 * (SAFE_BOTTOM - SAFE_TOP) / 3 and band[1] <= SAFE_BOTTOM


def test_without_faces_every_event_sits_in_the_lower_third_of_the_safe_zone(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path)
    bands = event_bands(parse_ass(Path(path)))
    assert len(bands) == 2
    for b in bands:
        assert SAFE_TOP <= b[0] and b[1] <= SAFE_BOTTOM
        assert in_lower_third_of_safe_zone(b)


def test_style_keeps_the_right_margin_clear_for_tiktok_icons(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path)
    # colonne d'icones TikTok a droite : au moins ~11 % de la largeur (120 px)
    assert int(parse_ass(Path(path))["style"]["MarginR"]) >= 120

    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, config=make_config(tmp_path, margin_right=210), force=True)
    assert parse_ass(Path(path))["style"]["MarginR"] == "210"


def test_safe_zone_comes_from_config(tmp_path, video_dir):
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, config=make_config(tmp_path, safe_zone=[0.30, 0.60]))
    for b in event_bands(parse_ass(Path(path))):
        assert 0.30 * H <= b[0] and b[1] <= 0.60 * H


def test_face_in_the_lower_part_moves_subtitles_just_above_it_not_to_the_top(tmp_path, video_dir):
    # constat du clip 00 : visage qui touche le bas -> sous-titres tout en haut,
    # sous l'interface TikTok. Ils restent dans la zone sure, au-dessus du visage.
    face = (0.55, 0.80)
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, avoid_zones=zones((0.0, 10.0, [face])))
    for b in event_bands(parse_ass(Path(path))):
        assert SAFE_TOP <= b[0] and b[1] <= SAFE_BOTTOM
        assert overlap(b, px(face)) == 0
        # le plus bas possible au-dessus du visage : a moins d'un pas de lui
        assert b[1] >= px(face)[0] - 200


def test_each_event_takes_the_position_of_the_plan_it_is_shown_in(tmp_path, video_dir):
    # events : [monde bienvenue sur] 1.1-2.6, [GTA six.] 2.7-4.6
    face = (0.55, 0.80)
    avoid = zones((0.0, 2.65, [face]), (2.65, 10.0, []))
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, avoid_zones=avoid)
    first, second = event_bands(parse_ass(Path(path)))
    assert overlap(first, px(face)) == 0
    assert in_lower_third_of_safe_zone(second)
    assert first != second


def test_event_spanning_two_plans_avoids_the_faces_of_both(tmp_path, video_dir):
    upper, lower = (0.20, 0.45), (0.60, 0.80)
    # [monde bienvenue sur] 1.1-2.6 est a cheval sur les deux plans
    avoid = zones((0.0, 2.0, [upper]), (2.0, 10.0, [lower]))
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, avoid_zones=avoid)
    first = event_bands(parse_ass(Path(path)))[0]
    assert overlap(first, px(upper)) == 0 and overlap(first, px(lower)) == 0


def test_without_free_position_the_least_covering_one_is_taken_and_logged(tmp_path, video_dir, caplog):
    # visages de 20 % a 70 % : seule la bande 70-78 % (154 px) est libre, trop
    # petite pour le texte ; la position la plus basse est la moins recouvrante.
    face = (0.20, 0.70)
    with caplog.at_level("WARNING", logger="clipper.subtitles"), \
            llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, avoid_zones=zones((0.0, 10.0, [face])))
    for b in event_bands(parse_ass(Path(path))):
        assert b[1] == pytest.approx(SAFE_BOTTOM, abs=1)
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings and CLIP_ID in warnings[0].getMessage()


def test_free_position_logs_nothing(tmp_path, video_dir, caplog):
    with caplog.at_level("WARNING", logger="clipper.subtitles"), \
            llm.use_backend(FakeBackend([NO_EMPHASIS])):
        run(tmp_path, avoid_zones=zones((0.0, 10.0, [(0.55, 0.80)])))
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_hook_band_is_never_covered_even_to_avoid_a_face(tmp_path, video_dir):
    # zone sure elargie jusqu'en haut par la config : l'accroche (0-12 %, les
    # 2 premieres secondes du clip) reste interdite, meme si le visage pousse
    # les sous-titres vers le haut.
    hook = (0.0, 0.12)
    face = (0.30, 0.78)
    config = make_config(tmp_path, safe_zone=[0.0, 0.78])
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, config=config, avoid_zones=zones((0.0, 10.0, [face])),
                   reserved_zones=zones((1.0, 3.0, [hook])))
    bands = event_bands(parse_ass(Path(path)))
    for b in bands:
        assert overlap(b, px(hook)) == 0
        assert overlap(b, px(face)) == 0


def test_hook_band_leaves_no_candidate_is_an_error(tmp_path, video_dir):
    from clipper.subtitles import SubtitlesError

    config = make_config(tmp_path, safe_zone=[0.0, 0.3])
    with llm.use_backend(FakeBackend([NO_EMPHASIS])), pytest.raises(SubtitlesError):
        run(tmp_path, config=config, reserved_zones=zones((1.0, 3.0, [(0.0, 0.3)])))


# Cas reels du recadrage (reframe/<clip_id>.json), passes par pipeline.avoid_zones.


def reframe_plan(layout, faces, panels, start=0.0, end=10.0):
    return {"output": {"width": 1080, "height": 1920},
            "plans": [{"index": 0, "start": start, "end": end, "layout": layout,
                       "faces": faces, "panels": panels}]}


def rect(x, y, w, h, start=0.0, end=10.0):
    return {"start": start, "end": end, "x": x, "y": y, "w": w, "h": h}


def run_with_plan(tmp_path, plan):
    from clipper.pipeline import avoid_zones

    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, avoid_zones=avoid_zones(plan))
    return event_bands(parse_ass(Path(path)))


def test_split_layout_face_in_camera_panel(tmp_path, video_dir):
    # webcam en haut (0-768 px), visage y 100..300 sur 400 -> 192..576 px
    face = {"id": 0, "first": 0.0, "last": 10.0, "box": [800, 100, 1000, 300]}
    panels = [
        {"name": "camera", "dest": {"x": 0, "y": 0, "w": 1080, "h": 768}, "rects": [rect(700, 0, 400, 400)]},
        {"name": "gameplay", "dest": {"x": 0, "y": 768, "w": 1080, "h": 1152}, "rects": [rect(0, 0, 640, 1080)]},
    ]
    for b in run_with_plan(tmp_path, reframe_plan("split", [face], panels)):
        assert overlap(b, (192, 576)) == 0
        assert in_lower_third_of_safe_zone(b)


def test_blur_layout_face_in_main_band(tmp_path, video_dir):
    # fond flou + image entiere au centre (656..1264 px, echelle 608/1080) ;
    # visage y 200..700 source -> 768..1051 px.
    face = {"id": 0, "first": 0.0, "last": 10.0, "box": [700, 200, 1100, 700]}
    panels = [
        {"name": "background", "effect": "blur", "dest": {"x": 0, "y": 0, "w": 1080, "h": 1920},
         "rects": [rect(0, 0, 1920, 1080)]},
        {"name": "main", "dest": {"x": 0, "y": 656, "w": 1080, "h": 608}, "rects": [rect(0, 0, 1920, 1080)]},
    ]
    for b in run_with_plan(tmp_path, reframe_plan("fallback_blur", [face], panels)):
        assert overlap(b, (768, 1051)) == 0
        assert in_lower_third_of_safe_zone(b)


def test_single_layout_face_low_in_frame(tmp_path, video_dir):
    # cadre 608x1080 plein ecran (echelle 1920/1080) ; visage y 700..1000
    # source -> 1244..1778 px : couvre le tiers inferieur de la zone sure.
    face = {"id": 0, "first": 0.0, "last": 10.0, "box": [700, 700, 900, 1000]}
    panels = [{"name": "main", "dest": {"x": 0, "y": 0, "w": 1080, "h": 1920}, "rects": [rect(600, 0, 608, 1080)]}]
    for b in run_with_plan(tmp_path, reframe_plan("single", [face], panels)):
        assert overlap(b, (1244.4, 1777.8)) == 0
        assert SAFE_TOP <= b[0] and b[1] <= SAFE_BOTTOM


# --------------------------------------------------------------------------
# C8 (TASK-29cf) : apostrophe ou trait d'union colle rattache au mot precedent
# --------------------------------------------------------------------------


def event_tokens(ev: dict) -> list[str]:
    return [t for t in re.findall(r"\\k\d+(?:\\c[^}]*)?\}([^{]*)", ev["text"]) if t.strip()]


def test_glued_apostrophe_and_hyphen_tokens_stay_with_the_previous_word(tmp_path, video_dir):
    words = [
        # decoupe par jetons (4 par groupe) du clip 00 : "Donc deja il m" / "'a ..."
        _word(" Donc", 1.0, 1.1), _word(" déjà", 1.1, 1.2), _word(" il", 1.2, 1.3), _word(" m", 1.3, 1.4),
        _word("'a", 1.4, 1.5), _word(" menti,", 1.5, 1.8), _word(" il", 1.8, 1.9),
        _word(" n", 1.9, 2.0), _word("\u2019a", 2.0, 2.1), _word(" pas", 2.1, 2.2),
        _word(" dit", 2.2, 2.4), _word(" d", 2.4, 2.5), _word("'autrui", 2.5, 2.8),
        _word(" viens", 2.8, 3.0), _word("-tu", 3.0, 3.2), _word(" vraiment", 3.2, 3.6),
    ]
    (video_dir / "transcript.json").write_text(json.dumps(make_transcript(words)), encoding="utf-8")
    with llm.use_backend(FakeBackend([NO_EMPHASIS])):
        path = run(tmp_path, start=1.0, end=4.0)
    events = parse_ass(Path(path))["events"]
    tokens = [event_tokens(ev) for ev in events]
    assert [t for ev in tokens for t in ev] == [w["word"] for w in words]
    for ev in tokens:
        assert not ev[0].startswith(("'", "\u2019", "-"))
    # un mot avec son elision compte pour un : 4 mots au plus par groupe
    for ev in tokens:
        assert len([t for t in ev if not t.startswith(("'", "\u2019", "-"))]) <= 4


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
