"""Regroupement des tâches, graphe en lanes et liaison branche -> tâche."""
import ankviz


def task(id_, status, claimed_by=None):
    return {"id": id_, "short": id_[:9], "kind": "task", "status": status,
            "claimed_by": claimed_by, "title": id_}


def test_group_tasks_by_state_with_ready_vs_blocked():
    tasks = [
        task("TASK-aaaa0001", "done"),
        task("TASK-bbbb0002", "open"),          # bloquée par a (faite) -> prête
        task("TASK-cccc0003", "open"),          # bloquée par d (en cours) -> bloquée
        task("TASK-dddd0004", "in_progress", "bob@pc"),
        task("TASK-eeee0005", "closed"),
        task("TASK-ffff0006", "open"),          # sans bloqueur -> prête
        task("TASK-99990007", "open"),          # bloquée par e (fermée) -> prête
    ]
    edges = [("TASK-bbbb0002", "TASK-aaaa0001"),
             ("TASK-cccc0003", "TASK-dddd0004"),
             ("TASK-99990007", "TASK-eeee0005")]
    groups = ankviz.group_tasks(tasks, edges)
    assert groups == {
        "in_progress": ["TASK-dddd0004"],
        "ready": ["TASK-bbbb0002", "TASK-ffff0006", "TASK-99990007"],
        "blocked": ["TASK-cccc0003"],
        "done": ["TASK-aaaa0001"],
        "closed": ["TASK-eeee0005"],
    }


def test_layout_git_style_lanes_fork_and_merge():
    ids = ["A", "B", "C", "D", "E"]
    edges = [("B", "A"), ("C", "A"), ("D", "B"), ("D", "C")]
    g = ankviz.layout_graph(ids, edges)
    assert g["nodes"] == [
        {"id": "A", "row": 0, "lane": 0},
        {"id": "B", "row": 1, "lane": 0},
        {"id": "C", "row": 2, "lane": 1},
        {"id": "D", "row": 3, "lane": 0},
        {"id": "E", "row": 4, "lane": 0},
    ]
    assert g["edges"] == [
        {"from": "A", "to": "B", "lane": 0},
        {"from": "A", "to": "C", "lane": 1},
        {"from": "B", "to": "D", "lane": 0},
        {"from": "C", "to": "D", "lane": 0},  # rejoint la lane déjà réservée par D
    ]
    assert g["lanes"] == 2


def test_layout_puts_blockers_before_what_they_block_whatever_the_input_order():
    g = ankviz.layout_graph(["Z", "Y", "X"], [("Z", "Y"), ("Y", "X")])
    assert [n["id"] for n in g["nodes"]] == ["X", "Y", "Z"]
    assert {n["lane"] for n in g["nodes"]} == {0}


def test_branch_links_to_task_by_short_or_full_id():
    tasks = [task("TASK-7aca619df8f4", "in_progress"), task("TASK-476fdd9fb43c", "open")]
    assert ankviz.link_task("task/TASK-7aca-ank-viz", tasks) == "TASK-7aca619df8f4"
    assert ankviz.link_task("origin/feat/task-476fdd9fb43c", tasks) == "TASK-476fdd9fb43c"
    assert ankviz.link_task("main", tasks) is None


def test_layout_on_recorded_graph_stays_narrow():
    from pathlib import Path
    text = (Path(__file__).parent / "fixtures" / "graph.json").read_text(encoding="utf-8")
    import json
    ids = [t["id"] for t in json.loads(text)["tasks"]]
    g = ankviz.layout_graph(ids, ankviz.parse_edges(text))
    assert len(g["nodes"]) == 19
    assert g["lanes"] <= 8
    rows = {n["id"]: n["row"] for n in g["nodes"]}
    for task, blocker in ankviz.parse_edges(text):
        assert rows[blocker] < rows[task]


def test_group_tasks_open_task_with_live_claim_is_in_progress():
    # ank garde status "open" pendant un claim : seul claimed_by le révèle
    tasks = [task("TASK-aaaa0001", "open", "w-476f"),
             task("TASK-bbbb0002", "open")]
    groups = ankviz.group_tasks(tasks, [("TASK-bbbb0002", "TASK-aaaa0001")])
    assert groups["in_progress"] == ["TASK-aaaa0001"]
    assert groups["ready"] == []
    assert groups["blocked"] == ["TASK-bbbb0002"]
