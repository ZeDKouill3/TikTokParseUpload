"""tools/replay_jury.py : rejeu hors ligne du jury sur des posts dont la part
vue est connue (plan jury-retention). Tout tourne sur CPU avec FakeBackend ;
l'execution reelle (vrai Claude, quota) est optionnelle (CLIPPER_REAL_MODELS=1)."""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
import re
from pathlib import Path

import pytest

from clipper import llm, moments
from clipper.config import Config
from clipper.llm.fake import FakeBackend

REPO = Path(__file__).resolve().parents[1]
JUDGES = ("retention", "spectateur", "monteur", "avocat", "conformite")
# Part vue connue de 4 clips synthetiques k = 0..3.
PCT = [0.10, 0.20, 0.30, 0.40]


def _load_tool():
    spec = importlib.util.spec_from_file_location("_replay_jury_tool", REPO / "tools" / "replay_jury.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Dossier de travail : output/<video>/<clip>.json et posts.csv de 4 clips."""
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "output" / "vid"
    out.mkdir(parents=True)
    for k in range(4):
        sidecar = {"video_id": "vid", "clip_id": f"{k:02d}", "start": 100.0 * k, "end": 100.0 * k + 30.0,
                   "transcript": f"CLIPMARK{k} texte du clip numero {k}"}
        (out / f"{k:02d}.json").write_text(json.dumps(sidecar), encoding="utf-8")
    with (tmp_path / "posts.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["video_id", "clip_id", "pct_watched", "views"])
        w.writeheader()
        for k in range(4):
            w.writerow({"video_id": "vid", "clip_id": f"{k:02d}", "pct_watched": PCT[k], "views": 100})
    return tmp_path


def _config(root_dir):
    return Config(mode="auto", workspace_dir=root_dir / "workspace", output_dir=root_dir / "output", _sections={})


def _responder(table, perspectives=None):
    """Repond pour chaque juge (usage jury_<nom>) : note table[juge][k] a tous les criteres."""
    rubric = moments.load_rubric(moments.resolve_rubric_path("builtin:gaming-v2"))
    names = list(rubric["criteria"])

    def respond(request):
        judge = request.usage.removeprefix("jury_")
        if perspectives is not None:
            perspectives[judge] = request.prompt
        answer = []
        for chunk in request.prompt.split("\n### ")[1:]:
            ref = chunk.split("\n", 1)[0].strip()
            match = re.search(r"CLIPMARK(\d)", chunk)
            if not (ref and match):
                continue
            note = table[judge][int(match.group(1))]
            item = {"ref": ref, "argument": "arg", "scores": dict.fromkeys(names, note), "confidence": 80}
            props = request.schema["properties"]["candidates"]["items"]["properties"]
            if "veto" in props:
                item["veto"], item["veto_reason"] = False, ""
            answer.append(item)
        return {"candidates": answer}

    return respond


def test_replay_writes_spearman_per_judge_and_for_the_final_score(root):
    tool = _load_tool()
    table = {
        "retention": [2, 4, 6, 8],      # meme ordre que la part vue : rho = +1
        "spectateur": [8, 6, 4, 2],     # ordre inverse : rho = -1
        "monteur": [2, 6, 4, 8],        # rangs 1,3,2,4 vs 1,2,3,4 : rho = 0,8
        "avocat": [5, 5, 5, 5],         # constant : rho non defini (None)
        "conformite": [2, 4, 6, 8],
    }
    with llm.use_backend(FakeBackend([_responder(table)])):
        result = tool.replay(root / "posts.csv", rubric="builtin:gaming-v2", config=_config(root), root=root)

    rho = result["spearman"]["judges"]
    assert rho["retention"] == pytest.approx(1.0)
    assert rho["spectateur"] == pytest.approx(-1.0)
    assert rho["monteur"] == pytest.approx(0.8)
    assert rho["avocat"] is None
    assert result["n"] == 4
    # note finale = mediane des juges : [2,6,4,8] / [8,6,4,2] / ... ; calculee a la main :
    # clip0 : 2,8,2,5,2 -> 2 ; clip1 : 4,6,6,5,4 -> 5 ; clip2 : 6,4,4,5,6 -> 5 ; clip3 : 8,2,8,5,8 -> 8
    # rangs de la note finale : 1, 2,5 ; 2,5 ; 4 -> rho avec 1,2,3,4 = 0,9487
    assert result["spearman"]["final"] == pytest.approx(0.9487, abs=1e-3)
    assert result["rubric"] == "builtin:gaming-v2"


def test_replay_gives_each_clip_text_to_the_jury_and_uses_the_given_perspective(root, tmp_path):
    tool = _load_tool()
    perspective = root / "persp.md"
    perspective.write_text("PERSPECTIVE-DE-TEST rétention v1\n", encoding="utf-8")
    seen = {}
    table = {j: [1, 2, 3, 4] for j in JUDGES}
    with llm.use_backend(FakeBackend([_responder(table, seen)])):
        result = tool.replay(
            root / "posts.csv", rubric="builtin:gaming-v2", perspective=perspective,
            config=_config(root), root=root,
        )

    assert "PERSPECTIVE-DE-TEST" in seen["retention"]
    assert "PERSPECTIVE-DE-TEST" not in seen["spectateur"]
    assert all(f"CLIPMARK{k}" in seen["retention"] for k in range(4))
    assert result["perspective"] == str(perspective)


def test_replay_skips_posts_without_pct_watched_and_says_so(root):
    tool = _load_tool()
    rows = list(csv.DictReader((root / "posts.csv").open(encoding="utf-8")))
    rows[3]["pct_watched"] = ""
    with (root / "posts.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    table = {j: [1, 2, 3, 4] for j in JUDGES}
    with llm.use_backend(FakeBackend([_responder(table)])):
        result = tool.replay(root / "posts.csv", config=_config(root), root=root)

    assert result["n"] == 3
    assert result["skipped"] == [{"video_id": "vid", "clip_id": "03", "reason": "pct_watched absent"}]


def test_replay_missing_sidecar_is_a_visible_error_not_a_skipped_clip(root):
    tool = _load_tool()
    (root / "output" / "vid" / "02.json").unlink()

    with pytest.raises(tool.ReplayError, match="02.json"):
        tool.replay(root / "posts.csv", config=_config(root), root=root)


def test_replay_unknown_rubric_is_an_error(root):
    tool = _load_tool()

    with pytest.raises(moments.MomentsError, match="builtin:inconnue"):
        tool.replay(root / "posts.csv", rubric="builtin:inconnue", config=_config(root), root=root)


def test_cli_writes_the_result_as_json(root, capsys):
    tool = _load_tool()
    table = {j: [1, 2, 3, 4] for j in JUDGES}
    out = root / "replay.json"
    with llm.use_backend(FakeBackend([_responder(table)])):
        code = tool.main([str(root / "posts.csv"), "--root", str(root), "--out", str(out)], config=_config(root))

    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert math.isclose(data["spearman"]["judges"]["retention"], 1.0)
    assert "retention" in capsys.readouterr().out


@pytest.mark.skipif(os.environ.get("CLIPPER_REAL_MODELS") != "1", reason="vrai Claude (quota) : CLIPPER_REAL_MODELS=1")
def test_replay_real_jury_on_the_known_posts():
    tool = _load_tool()
    posts = REPO / "research" / "perf-0910" / "posts.csv"
    if not posts.exists():
        pytest.skip("research/perf-0910/posts.csv absent")
    result = tool.replay(posts, rubric="builtin:gaming-v2", root=REPO)
    assert result["n"] > 0 and "final" in result["spearman"]
