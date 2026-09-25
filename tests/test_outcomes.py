from __future__ import annotations

from pathlib import Path

import pytest


# --------------------------------------------------------------------------
# record() : lie un resultat a la trace du jury (video_id, clip_id, moment_id)
# --------------------------------------------------------------------------


def test_record_carries_video_id_clip_id_and_moment_id(isolated_cwd):
    from clipper.outcomes import record

    entry = record(
        video_id="abc123",
        clip_id="03",
        moment_id=3,
        qa={"status": "passed", "issues": []},
        path=isolated_cwd / "outcomes.jsonl",
    )

    assert entry["video_id"] == "abc123"
    assert entry["clip_id"] == "03"
    assert entry["moment_id"] == 3


def test_record_carries_qa_verdict_and_defects(isolated_cwd):
    from clipper.outcomes import record

    qa = {"status": "rejected", "issues": [{"type": "face_cut", "detail": "...", "source": "llm"}]}

    entry = record(
        video_id="abc123", clip_id="03", moment_id=3, qa=qa, path=isolated_cwd / "outcomes.jsonl"
    )

    assert entry["qa"] == qa


def test_record_defaults_human_decision_to_none(isolated_cwd):
    from clipper.outcomes import record

    entry = record(
        video_id="abc123",
        clip_id="03",
        moment_id=3,
        qa={"status": "passed", "issues": []},
        path=isolated_cwd / "outcomes.jsonl",
    )

    assert entry["human_decision"] is None


def test_record_carries_optional_human_decision(isolated_cwd):
    from clipper.outcomes import record

    entry = record(
        video_id="abc123",
        clip_id="03",
        moment_id=3,
        qa={"status": "passed", "issues": []},
        human_decision="approved",
        path=isolated_cwd / "outcomes.jsonl",
    )

    assert entry["human_decision"] == "approved"


def test_record_stamps_recorded_at(isolated_cwd):
    from clipper.outcomes import record

    entry = record(
        video_id="abc123",
        clip_id="03",
        moment_id=3,
        qa={"status": "passed", "issues": []},
        path=isolated_cwd / "outcomes.jsonl",
    )

    assert "recorded_at" in entry and entry["recorded_at"]


# --------------------------------------------------------------------------
# journal append-only sous state/
# --------------------------------------------------------------------------


def test_default_journal_path_lives_under_state(isolated_cwd):
    from clipper.outcomes import CONFIG_DEFAULTS

    journal_path = Path(CONFIG_DEFAULTS["journal_path"])

    assert journal_path.parts[0] == "state"


def test_default_journal_path_lives_outside_the_workspace_and_output_directories():
    from clipper.config import DEFAULTS as CONFIG_DEFAULTS_TOP
    from clipper.outcomes import CONFIG_DEFAULTS

    workspace_dir = CONFIG_DEFAULTS_TOP["workspace_dir"]
    output_dir = CONFIG_DEFAULTS_TOP["output_dir"]
    journal_path = Path(CONFIG_DEFAULTS["journal_path"])

    assert workspace_dir not in journal_path.parts
    assert output_dir not in journal_path.parts


def test_journal_path_is_configurable_through_the_outcomes_config_section(isolated_cwd):
    from clipper.config import load_config

    (isolated_cwd / "config.toml").write_text(
        '[outcomes]\njournal_path = "elsewhere/outcomes.jsonl"\n'
    )

    config = load_config(isolated_cwd / "config.toml")

    assert config.section("outcomes")["journal_path"] == "elsewhere/outcomes.jsonl"


def test_record_appends_successive_results_to_the_same_journal_file(isolated_cwd):
    from clipper.outcomes import record

    journal = isolated_cwd / "outcomes.jsonl"

    record(video_id="v1", clip_id="01", moment_id=1, qa={"status": "passed", "issues": []}, path=journal)
    record(video_id="v2", clip_id="02", moment_id=2, qa={"status": "rejected", "issues": []}, path=journal)

    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_record_creates_missing_parent_directories(isolated_cwd):
    from clipper.outcomes import record

    journal = isolated_cwd / "state" / "nested" / "outcomes.jsonl"

    record(video_id="v1", clip_id="01", moment_id=1, qa={"status": "passed", "issues": []}, path=journal)

    assert journal.exists()


# --------------------------------------------------------------------------
# import_stats() : statistiques de plateforme importees d'un CSV
# --------------------------------------------------------------------------


def _write_stats_csv(path: Path, rows: list[dict]) -> None:
    import csv

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["clip_id", "views", "retention_3s", "watched_full", "shares", "date"])
        writer.writeheader()
        writer.writerows(rows)


def test_import_stats_appends_one_entry_per_csv_row(isolated_cwd):
    from clipper.outcomes import import_stats

    csv_path = isolated_cwd / "stats.csv"
    _write_stats_csv(
        csv_path,
        [
            {"clip_id": "01", "views": "1000", "retention_3s": "0.62", "watched_full": "0.18", "shares": "5", "date": "2026-09-20"},
            {"clip_id": "02", "views": "500", "retention_3s": "0.40", "watched_full": "0.10", "shares": "1", "date": "2026-09-21"},
        ],
    )

    journal = isolated_cwd / "outcomes.jsonl"
    entries = import_stats(csv_path, path=journal)

    assert len(entries) == 2
    assert journal.read_text(encoding="utf-8").count("\n") == 2


def test_import_stats_entry_carries_clip_id_and_stats_fields(isolated_cwd):
    from clipper.outcomes import import_stats

    csv_path = isolated_cwd / "stats.csv"
    _write_stats_csv(
        csv_path,
        [{"clip_id": "01", "views": "1000", "retention_3s": "0.62", "watched_full": "0.18", "shares": "5", "date": "2026-09-20"}],
    )

    entries = import_stats(csv_path, path=isolated_cwd / "outcomes.jsonl")

    entry = entries[0]
    assert entry["clip_id"] == "01"
    assert entry["stats"] == {
        "views": 1000,
        "retention_3s": 0.62,
        "watched_full": 0.18,
        "shares": 5,
        "date": "2026-09-20",
    }


def test_import_stats_rejects_csv_missing_a_documented_column(isolated_cwd):
    from clipper.outcomes import OutcomesError, import_stats

    csv_path = isolated_cwd / "stats.csv"
    csv_path.write_text("clip_id,views\n01,1000\n", encoding="utf-8")

    with pytest.raises(OutcomesError):
        import_stats(csv_path, path=isolated_cwd / "outcomes.jsonl")


# --------------------------------------------------------------------------
# read() : lecture filtree par periode
# --------------------------------------------------------------------------


def test_read_returns_empty_list_when_no_journal_exists(isolated_cwd):
    from clipper.outcomes import read

    assert read(path=isolated_cwd / "outcomes.jsonl") == []


def test_read_returns_all_entries_without_period_filter(isolated_cwd):
    from clipper.outcomes import read, record

    journal = isolated_cwd / "outcomes.jsonl"
    record(video_id="v1", clip_id="01", moment_id=1, qa={"status": "passed", "issues": []}, path=journal)
    record(video_id="v2", clip_id="02", moment_id=2, qa={"status": "passed", "issues": []}, path=journal)

    assert len(read(path=journal)) == 2


def test_read_filters_entries_recorded_before_since(isolated_cwd):
    from clipper.outcomes import read

    journal = isolated_cwd / "outcomes.jsonl"
    journal.write_text(
        '{"video_id": "old", "recorded_at": "2026-01-01T00:00:00+00:00"}\n'
        '{"video_id": "new", "recorded_at": "2026-09-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )

    result = read(path=journal, since="2026-06-01")

    assert [e["video_id"] for e in result] == ["new"]


def test_read_filters_entries_recorded_after_until(isolated_cwd):
    from clipper.outcomes import read

    journal = isolated_cwd / "outcomes.jsonl"
    journal.write_text(
        '{"video_id": "old", "recorded_at": "2026-01-01T00:00:00+00:00"}\n'
        '{"video_id": "new", "recorded_at": "2026-09-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )

    result = read(path=journal, until="2026-06-01")

    assert [e["video_id"] for e in result] == ["old"]


def test_read_since_and_until_together_bound_a_window(isolated_cwd):
    from clipper.outcomes import read

    journal = isolated_cwd / "outcomes.jsonl"
    journal.write_text(
        '{"video_id": "before", "recorded_at": "2026-01-01T00:00:00+00:00"}\n'
        '{"video_id": "inside", "recorded_at": "2026-06-15T00:00:00+00:00"}\n'
        '{"video_id": "after", "recorded_at": "2026-12-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )

    result = read(path=journal, since="2026-06-01", until="2026-07-01")

    assert [e["video_id"] for e in result] == ["inside"]


# --------------------------------------------------------------------------
# aucun reseau
# --------------------------------------------------------------------------


def test_module_imports_no_networking_library():
    import ast

    from clipper import outcomes

    source = Path(outcomes.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"requests", "urllib", "http", "socket", "httpx", "aiohttp"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not (imported & forbidden)
