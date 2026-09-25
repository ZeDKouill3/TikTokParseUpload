from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from clipper import llm
from clipper.config import Config
from clipper.llm.fake import FakeBackend

VIDEO_ID = "abcdefghijk"

# Candidats de moments.json : un moment retenu [100-130] et un rejete
# [300-330] ; fenetres +/-10 s : [90-140] et [290-340].
MOMENTS = {
    "video_id": VIDEO_ID,
    "moments": [{"id": 0, "start": 100.0, "end": 130.0, "hook_text": "accroche"}],
    "rejected": [{"start": 300.0, "end": 330.0, "reason": "score 55.0 < min_score 60"}],
}

# Images cles de scenes.json ; seules 91, 115, 139, 295 et 335 tombent
# dans une fenetre.
TIMECODES = [50.0, 89.0, 91.0, 115.0, 139.0, 141.0, 200.0, 295.0, 335.0, 345.0]


def frame_name(t):
    return f"frames/f{int(t):04d}.jpg"


def seed_scenes(video_dir, timecodes=TIMECODES):
    (video_dir / "frames").mkdir(exist_ok=True)
    frames = []
    for n, t in enumerate(timecodes):
        (video_dir / frame_name(t)).write_bytes(b"\xff\xd8\xff\xe0 jpeg de test")
        frames.append({"path": frame_name(t), "timecode": t, "scene": n})
    (video_dir / "scenes.json").write_text(
        json.dumps({"scenes": [{"start": 0.0, "end": 500.0}], "frames": frames}), encoding="utf-8"
    )


@pytest.fixture
def video_dir(tmp_path):
    d = tmp_path / "workspace" / VIDEO_ID
    d.mkdir(parents=True)
    (d / "moments.json").write_text(json.dumps(MOMENTS), encoding="utf-8")
    seed_scenes(d)
    return d


def make_config(tmp_path, **sections):
    return Config(
        mode="review",
        workspace_dir=tmp_path / "workspace",
        output_dir=tmp_path / "output",
        _sections=sections,
    )


def describe_all(striking_at=(), tags=("plan large",)):
    """Reponse fake : decrit chaque image du lot, marquante si son timecode
    (lu dans le prompt) est dans ``striking_at``."""

    def answer(request):
        frames = []
        for n, _ in enumerate(request.images):
            t = float(request.prompt.split(f"Image {n} : ")[1].split(" s")[0])
            frames.append(
                {
                    "index": n,
                    "description": f"image a {t:.1f}",
                    "tags": list(tags),
                    "striking": t in striking_at,
                }
            )
        return {"frames": frames}

    return answer


def run_vision(tmp_path, responses, **settings):
    from clipper.vision import run

    fake = FakeBackend(responses)
    config = make_config(tmp_path, vision=settings) if settings else make_config(tmp_path)
    with llm.use_backend(fake):
        path = run(VIDEO_ID, tmp_path / "workspace", config=config)
    return fake, path


def sent_images(fake, video_dir):
    return [p.relative_to(video_dir).as_posix() for call in fake.calls for p in call.images]


# --------------------------------------------------------------------------
# Selection des images : fenetres des candidats +/-10 s
# --------------------------------------------------------------------------


def test_only_keyframes_inside_candidate_windows_are_sent(tmp_path, video_dir):
    fake, _ = run_vision(tmp_path, [describe_all()] * 5)

    assert sorted(sent_images(fake, video_dir)) == [
        "frames/f0091.jpg",
        "frames/f0115.jpg",
        "frames/f0139.jpg",
        "frames/f0295.jpg",
        "frames/f0335.jpg",
    ]


def test_no_candidate_window_means_no_llm_call(tmp_path, video_dir):
    (video_dir / "moments.json").write_text(
        json.dumps({"video_id": VIDEO_ID, "moments": [], "rejected": []}), encoding="utf-8"
    )

    fake, path = run_vision(tmp_path, [])

    assert fake.calls == []
    assert json.loads(path.read_text(encoding="utf-8"))["frames"] == []


def test_rejection_without_bounds_opens_no_window(tmp_path, video_dir):
    data = {**MOMENTS, "rejected": [{"reason": "bornes absentes"}]}
    (video_dir / "moments.json").write_text(json.dumps(data), encoding="utf-8")

    fake, _ = run_vision(tmp_path, [describe_all()] * 5)

    assert sorted(sent_images(fake, video_dir)) == ["frames/f0091.jpg", "frames/f0115.jpg", "frames/f0139.jpg"]


# --------------------------------------------------------------------------
# Appel LLM : usage vision, images jointes, par lots
# --------------------------------------------------------------------------


def test_frames_are_described_by_llm_vision_in_batches(tmp_path, video_dir):
    fake, _ = run_vision(tmp_path, [describe_all()] * 3, batch_size=2)

    assert [c.usage for c in fake.calls] == ["vision", "vision", "vision"]
    assert [len(c.images) for c in fake.calls] == [2, 2, 1]
    assert all(p.is_file() for c in fake.calls for p in c.images)
    assert "115.0 s" in fake.calls[0].prompt


def test_answer_missing_a_frame_is_a_failure_and_writes_nothing(tmp_path, video_dir):
    short = {"frames": [{"index": 0, "description": "x", "tags": [], "striking": False}]}

    with pytest.raises(llm.SchemaError):
        run_vision(tmp_path, [short], batch_size=2)
    assert not (video_dir / "vision.json").exists()


def test_answer_with_duplicate_index_is_a_failure(tmp_path, video_dir):
    dup = {"frames": [{"index": 0, "description": "x", "tags": [], "striking": False}] * 2}

    with pytest.raises(llm.SchemaError, match="index"):
        run_vision(tmp_path, [dup], batch_size=2)
    assert not (video_dir / "vision.json").exists()


def test_llm_unavailable_propagates_and_writes_nothing(tmp_path, video_dir):
    with pytest.raises(llm.TransientLLMError):
        run_vision(tmp_path, [llm.TransientLLMError("quota")])
    assert not (video_dir / "vision.json").exists()


# --------------------------------------------------------------------------
# Sortie : vision.json
# --------------------------------------------------------------------------


def test_writes_vision_json_with_timecode_description_tags(tmp_path, video_dir):
    _, path = run_vision(tmp_path, [describe_all(striking_at=(115.0,), tags=("explosion", "foule"))] * 5)

    assert path == video_dir / "vision.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["frames"][:2] == [
        {"timecode": 91.0, "path": "frames/f0091.jpg", "description": "image a 91.0",
         "tags": ["explosion", "foule"], "striking": False},
        {"timecode": 115.0, "path": "frames/f0115.jpg", "description": "image a 115.0",
         "tags": ["explosion", "foule"], "striking": True},
    ]
    assert [f["timecode"] for f in data["frames"]] == [91.0, 115.0, 139.0, 295.0, 335.0]


def test_existing_result_is_not_recomputed_unless_forced(tmp_path, video_dir):
    from clipper.vision import run

    (video_dir / "vision.json").write_text('{"frames": []}', encoding="utf-8")
    fake = FakeBackend([])
    with llm.use_backend(fake):
        run(VIDEO_ID, tmp_path / "workspace", config=make_config(tmp_path))
    assert fake.calls == []

    fake = FakeBackend([describe_all()] * 5)
    with llm.use_backend(fake):
        run(VIDEO_ID, tmp_path / "workspace", config=make_config(tmp_path), force=True)
    assert len(json.loads((video_dir / "vision.json").read_text(encoding="utf-8"))["frames"]) == 5


def test_missing_input_is_an_error(tmp_path, video_dir):
    from clipper.vision import VisionError

    (video_dir / "moments.json").unlink()
    with pytest.raises(VisionError, match="moments.json"):
        run_vision(tmp_path, [])


def test_missing_frame_file_is_an_error(tmp_path, video_dir):
    from clipper.vision import VisionError

    (video_dir / "frames" / "f0115.jpg").unlink()
    with pytest.raises(VisionError, match="f0115.jpg"):
        run_vision(tmp_path, [describe_all()] * 5)


def test_vision_section_is_configurable(tmp_path):
    config = make_config(tmp_path)
    assert config.section("vision")["window_seconds"] == 10


# --------------------------------------------------------------------------
# moments relance avec vision.json : les notes peuvent changer
# --------------------------------------------------------------------------

RUBRIC = """
min_score = 60
trend_keywords = []

[criteria.hook]
weight = 3
question = "Accroche ?"
[criteria.standalone]
weight = 3
question = "Autonome ?"
[criteria.payoff]
weight = 2
question = "Chute ?"
[criteria.emotion]
weight = 2
question = "Reaction forte ?"
[criteria.value]
weight = 2
question = "Info ?"
[criteria.trend]
weight = 1
question = "Tendance ?"

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
sponsorblock_categories = ["sponsor"]
"""


def seed_moments_inputs(tmp_path, video_dir):
    segments = []
    for k in range(100):
        start = 5 * k + 0.25
        words = [
            {"word": f" mot{k}_{i}" + ("." if i == 4 else ""), "start": start + i * 0.9,
             "end": start + i * 0.9 + 0.8, "probability": 0.9}
            for i in range(5)
        ]
        segments.append({"id": k, "start": words[0]["start"], "end": words[-1]["end"],
                         "text": "".join(w["word"] for w in words), "words": words})
    (video_dir / "transcript.json").write_text(json.dumps({"segments": segments}), encoding="utf-8")
    (video_dir / "meta.json").write_text(json.dumps({"title": "t", "duration": 500.0}), encoding="utf-8")
    (video_dir / "audio.json").write_text(json.dumps({"peaks": []}), encoding="utf-8")
    rubric = tmp_path / "rubric.toml"
    rubric.write_text(RUBRIC, encoding="utf-8")
    return rubric


def emotion_from_prompt(request):
    """Fake moments : emotion 9 si une image marquante est decrite dans le
    prompt, 5 sinon."""
    emotion = 9 if "(marquant)" in request.prompt else 5
    return {
        "moments": [
            {
                "hook_text": "accroche", "start": 100.25, "end": 129.65, "format": "single",
                "part_breaks": [], "justification": "ca marche",
                "scores": {"hook": 9, "standalone": 8, "payoff": 7, "emotion": emotion, "value": 5, "trend": 0},
            }
        ]
    }


def test_rerun_moments_revises_emotion_from_a_striking_description(tmp_path):
    from clipper.moments import run as run_moments
    from clipper.vision import run as run_vision_step

    video_dir = tmp_path / "workspace" / VIDEO_ID
    video_dir.mkdir(parents=True)
    seed_scenes(video_dir)
    rubric = seed_moments_inputs(tmp_path, video_dir)
    config = make_config(tmp_path, moments={"rubric_path": str(rubric)})
    workspace = tmp_path / "workspace"

    with llm.use_backend(FakeBackend([emotion_from_prompt])):
        run_moments(VIDEO_ID, workspace, config=config)
    before = json.loads((video_dir / "moments.json").read_text(encoding="utf-8"))
    assert before["moments"][0]["scores"]["emotion"] == 5

    with llm.use_backend(FakeBackend([describe_all(striking_at=(115.0,))] * 5)):
        run_vision_step(VIDEO_ID, workspace, config=config)

    with llm.use_backend(FakeBackend([emotion_from_prompt])) as fake:
        run_moments(VIDEO_ID, workspace, config=config, force=True)
    assert "image a 115.0 (marquant)" in fake.calls[0].prompt
    after = json.loads((video_dir / "moments.json").read_text(encoding="utf-8"))
    assert after["moments"][0]["scores"]["emotion"] == 9
    assert after["moments"][0]["bonus"]["visual"] == 2


# --------------------------------------------------------------------------
# Integration reelle (VLM ou Claude) : sautee par defaut
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CLIPPER_CLAUDE_INTEGRATION") != "1",
    reason="integration Claude : definir CLIPPER_CLAUDE_INTEGRATION=1 (consomme du quota)",
)
def test_real_llm_describes_a_real_frame(tmp_path, video_dir):
    import cv2
    import numpy as np

    from clipper.vision import run

    img = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(img, "BOOM", (180, 200), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 255), 8)
    for t in TIMECODES:
        cv2.imwrite(str(video_dir / frame_name(t)), img)

    path = run(VIDEO_ID, tmp_path / "workspace", config=make_config(tmp_path))

    frames = json.loads(Path(path).read_text(encoding="utf-8"))["frames"]
    assert len(frames) == 5
    assert all(f["description"].strip() for f in frames)
