from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_record_accepted_decision_carries_video_id_moment_texte_and_horodatage(isolated_cwd):
    from clipper.feedback import record

    moment = {"start": 12.0, "end": 34.0, "score": 78}

    entry = record(
        video_id="abc123",
        moment=moment,
        decision="accepted",
        texte_moment="c'est un moment fort",
        path=isolated_cwd / "journal.jsonl",
    )

    assert entry["video_id"] == "abc123"
    assert entry["moment"] == moment
    assert entry["texte_moment"] == "c'est un moment fort"
    assert entry["decision"] == "accepted"
    assert "horodatage" in entry and entry["horodatage"]


def test_record_rejected_decision_with_optional_commentaire(isolated_cwd):
    from clipper.feedback import record

    entry = record(
        video_id="abc123",
        moment={"start": 1.0, "end": 2.0},
        decision="rejected",
        texte_moment="hors sujet",
        commentaire="pas assez fort",
        path=isolated_cwd / "journal.jsonl",
    )

    assert entry["decision"] == "rejected"
    assert entry["commentaire"] == "pas assez fort"


def test_record_adjusted_decision_carries_the_adjusted_bounds_in_moment(isolated_cwd):
    from clipper.feedback import record

    adjusted_moment = {"start": 5.0, "end": 40.0}

    entry = record(
        video_id="abc123",
        moment=adjusted_moment,
        decision="adjusted",
        texte_moment="bon moment, bornes resserrees",
        path=isolated_cwd / "journal.jsonl",
    )

    assert entry["decision"] == "adjusted"
    assert entry["moment"] == adjusted_moment


def test_record_rejects_unknown_decision(isolated_cwd):
    from clipper.feedback import FeedbackError, record

    import pytest

    with pytest.raises(FeedbackError):
        record(
            video_id="abc123",
            moment={},
            decision="maybe",
            texte_moment="...",
            path=isolated_cwd / "journal.jsonl",
        )


def test_record_defaults_commentaire_to_none(isolated_cwd):
    from clipper.feedback import record

    entry = record(
        video_id="abc123",
        moment={},
        decision="accepted",
        texte_moment="...",
        path=isolated_cwd / "journal.jsonl",
    )

    assert entry["commentaire"] is None


def test_record_appends_successive_decisions_to_the_same_journal_file(isolated_cwd):
    from clipper.feedback import record

    journal = isolated_cwd / "journal.jsonl"

    record(video_id="v1", moment={}, decision="accepted", texte_moment="a", path=journal)
    record(video_id="v2", moment={}, decision="rejected", texte_moment="b", path=journal)

    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_default_journal_path_lives_outside_the_workspace_directory():
    from clipper.config import DEFAULTS as CONFIG_DEFAULTS_TOP
    from clipper.feedback import CONFIG_DEFAULTS

    workspace_dir = CONFIG_DEFAULTS_TOP["workspace_dir"]
    journal_path = Path(CONFIG_DEFAULTS["journal_path"])

    assert workspace_dir not in journal_path.parts


def test_journal_path_is_configurable_through_the_feedback_config_section(isolated_cwd):
    from clipper.config import load_config

    (isolated_cwd / "config.toml").write_text(
        '[feedback]\njournal_path = "elsewhere/journal.jsonl"\n'
    )

    config = load_config(isolated_cwd / "config.toml")

    assert config.section("feedback")["journal_path"] == "elsewhere/journal.jsonl"


def _seed(journal, decisions):
    """Record one decision per entry in decisions, in order, video_id = label."""
    from clipper.feedback import record

    for label, decision in decisions:
        record(video_id=label, moment={}, decision=decision, texte_moment=label, path=journal)


def test_examples_returns_empty_list_when_no_journal_exists(isolated_cwd):
    from clipper.feedback import examples

    result = examples(4, path=isolated_cwd / "journal.jsonl")

    assert result == []


def test_examples_returns_k_examples_balanced_positive_negative(isolated_cwd):
    from clipper.feedback import examples

    journal = isolated_cwd / "journal.jsonl"
    _seed(
        journal,
        [
            ("p1", "accepted"),
            ("n1", "rejected"),
            ("p2", "accepted"),
            ("n2", "rejected"),
            ("p3", "accepted"),
            ("n3", "rejected"),
        ],
    )

    result = examples(4, path=journal)

    labels = {e["video_id"] for e in result}
    assert len(result) == 4
    assert len(labels & {"p2", "p3"}) == 2
    assert len(labels & {"n2", "n3"}) == 2


def test_examples_treats_adjusted_as_positive(isolated_cwd):
    from clipper.feedback import examples

    journal = isolated_cwd / "journal.jsonl"
    _seed(journal, [("p1", "adjusted"), ("n1", "rejected")])

    result = examples(2, path=journal)

    decisions = {e["video_id"]: e["decision"] for e in result}
    assert decisions == {"p1": "adjusted", "n1": "rejected"}


def test_examples_fills_from_the_larger_pool_when_the_other_side_is_scarce(isolated_cwd):
    from clipper.feedback import examples

    journal = isolated_cwd / "journal.jsonl"
    _seed(
        journal,
        [
            ("p1", "accepted"),
            ("p2", "accepted"),
            ("p3", "accepted"),
            ("p4", "accepted"),
            ("p5", "accepted"),
            ("n1", "rejected"),
        ],
    )

    result = examples(4, path=journal)

    assert len(result) == 4
    labels = [e["video_id"] for e in result]
    assert labels.count("n1") == 1
    assert sum(1 for l in labels if l.startswith("p")) == 3


def test_examples_are_ordered_most_recent_first(isolated_cwd):
    from clipper.feedback import examples

    journal = isolated_cwd / "journal.jsonl"
    _seed(journal, [("p1", "accepted"), ("n1", "rejected"), ("p2", "accepted"), ("n2", "rejected")])

    result = examples(4, path=journal)

    assert [e["video_id"] for e in result] == ["n2", "p2", "n1", "p1"]


def test_examples_entries_are_ready_to_inject_into_a_prompt(isolated_cwd):
    from clipper.feedback import examples, record

    journal = isolated_cwd / "journal.jsonl"
    record(
        video_id="v1",
        moment={"start": 1.0, "end": 2.0},
        decision="accepted",
        texte_moment="un moment fort",
        commentaire="parfait",
        path=journal,
    )

    result = examples(1, path=journal)

    entry = result[0]
    assert entry.keys() >= {
        "video_id",
        "moment",
        "texte_moment",
        "decision",
        "commentaire",
        "horodatage",
    }
