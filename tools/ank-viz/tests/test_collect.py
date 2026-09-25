"""Collecte bout en bout avec un runner qui rejoue les sorties enregistrées."""
import json
from pathlib import Path

import ankviz

FIX = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIX / name).read_text(encoding="utf-8")


class Replay:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["ank", "find"]:
            return fixture("find.json")
        if argv[:2] == ["ank", "graph"]:
            return fixture("graph.json")
        if argv[:2] == ["ank", "status"]:
            return fixture("status.json")
        if argv[:2] == ["ank", "show"]:
            name = "show_%s.json" % argv[2][:9]
            if (FIX / name).exists():
                return fixture(name)
            return json.dumps({"id": argv[2], "content": "---\nid: x\n---\n"})
        if argv[:2] == ["git", "for-each-ref"]:
            return fixture("for-each-ref.txt")
        if argv[:2] == ["git", "rev-list"]:
            return "2\t1\n" if argv[-1].endswith("ank-viz") else fixture("rev-list.txt")
        raise AssertionError("commande inattendue: %r" % argv)


def test_only_ank_json_and_git_are_called():
    run = Replay()
    ankviz.Collector(run).refresh()
    assert run.calls
    for argv in run.calls:
        assert argv[0] in ("ank", "git")
        if argv[0] == "ank":
            assert "--json" in argv


def test_state_carries_tasks_groups_documents_graph_branches():
    state = ankviz.Collector(Replay()).refresh()
    tasks = {t["id"]: t for t in state["tasks"]}
    assert tasks["TASK-7291d843d843"]["criterion"].startswith("Pour chaque clip")
    assert tasks["TASK-7aca619df8f4"]["claimed_by"] == "UP60041549@wl0023729"
    assert state["groups"]["in_progress"] == ["TASK-7aca619df8f4"]
    assert "TASK-476fdd9fb43c" in state["groups"]["ready"]
    assert "TASK-7291d843d843" in state["groups"]["blocked"]
    assert {(d["kind"], d["status"]) for d in state["documents"]} == {("adr", "accepted"), ("spec", "accepted")}
    assert len(state["documents"]) == 7
    assert len(state["graph"]["nodes"]) == 19
    branches = {b["name"]: b for b in state["branches"]}
    assert branches["task/TASK-7aca-ank-viz"]["task"] == "TASK-7aca619df8f4"
    assert branches["task/TASK-7aca-ank-viz"]["ahead"] == 1
    assert branches["task/TASK-7aca-ank-viz"]["behind"] == 2
    assert branches["origin/main"]["remote"] is True
    assert branches["main"]["task"] is None
    assert state["default_branch"] == "main"


def test_criteria_are_cached_while_the_corpus_hash_is_unchanged():
    run = Replay()
    c = ankviz.Collector(run)
    c.refresh()
    first = len([a for a in run.calls if a[:2] == ["ank", "show"]])
    run.calls.clear()
    c.refresh()
    assert first == 19
    assert [a for a in run.calls if a[:2] == ["ank", "show"]] == []


def test_quick_pass_publishes_everything_but_criteria_without_ank_show():
    run = Replay()
    state = ankviz.Collector(run).refresh(criteria=False)
    assert [a for a in run.calls if a[:2] == ["ank", "show"]] == []
    assert state["criteria_loading"] is True
    assert len(state["tasks"]) == 19
    assert all(t["criterion"] is None for t in state["tasks"])
    assert state["groups"]["in_progress"] == ["TASK-7aca619df8f4"]
    assert len(state["branches"]) == 3


def test_full_pass_reports_criteria_loaded():
    state = ankviz.Collector(Replay()).refresh()
    assert state["criteria_loading"] is False
