"""Journalisation de la consommation (TASK-68eb6f43765d) pour le backend
claude-cli specifiquement : extraction de usage/total_cost_usd depuis la
sortie de `claude -p --output-format json`."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import clipper.llm as llm
from clipper.config import Config

COLOR_SCHEMA = {
    "type": "object",
    "properties": {"couleur": {"type": "string"}},
    "required": ["couleur"],
    "additionalProperties": False,
}

# Sortie reelle de `claude -p --output-format json`, avec le champ ``usage``
# et ``total_cost_usd`` conserves cette fois (retires des enregistrements de
# tests/test_llm.py, mais necessaires ici pour la journalisation de
# consommation).
RECORDED_CLAUDE_CLI_WITH_USAGE = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "api_error_status": None,
    "num_turns": 2,
    "result": '{"couleur": "rouge"}',
    "session_id": "9f30ba08-d590-421a-b1ee-aaab1a469667",
    "total_cost_usd": 0.0123,
    "usage": {
        "input_tokens": 512,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 128,
        "output_tokens": 40,
    },
}


def make_config(**llm_table) -> Config:
    return Config(
        mode="review",
        workspace_dir=Path("workspace"),
        output_dir=Path("output"),
        _sections={"llm": llm_table} if llm_table else {},
    )


class FakeRun:
    """Stands in for subprocess.run: records the call, returns a canned
    CompletedProcess."""

    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[dict] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": list(cmd), **kwargs})
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


@pytest.fixture
def fake_run(monkeypatch):
    monkeypatch.setattr("clipper.llm.claude_cli.shutil.which", lambda command: None)

    def _install(stdout, returncode=0, stderr=""):
        run = FakeRun(stdout, returncode, stderr)
        monkeypatch.setattr("clipper.llm.claude_cli.subprocess.run", run)
        return run

    return _install


def test_claude_cli_usage_log_extracts_tokens_and_cost_from_recorded_output(fake_run, tmp_path):
    fake_run(json.dumps(RECORDED_CLAUDE_CLI_WITH_USAGE))
    usage_log_path = tmp_path / "llm_usage.jsonl"

    out = llm.ask(
        "vision", "De quelle couleur ?", [], COLOR_SCHEMA,
        config=make_config(), usage_log_path=usage_log_path,
    )

    assert out == {"couleur": "rouge"}
    lines = [json.loads(line) for line in usage_log_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    entry = lines[0]
    assert entry["usage"] == "vision"
    assert entry["model"] == "sonnet"
    assert entry["input_tokens"] == 512
    assert entry["output_tokens"] == 40
    assert entry["cache_read_tokens"] == 128
    assert entry["cost_usd"] == pytest.approx(0.0123)
    assert isinstance(entry["duration_s"], float)
    assert entry["duration_s"] >= 0
    assert "T" in entry["timestamp"]


def test_claude_cli_usage_log_writes_null_fields_when_usage_is_absent(fake_run, tmp_path):
    # Sortie sans champ usage/total_cost_usd : aucune valeur inventee (ADR-ad2e).
    recorded_without_usage = dict(RECORDED_CLAUDE_CLI_WITH_USAGE)
    del recorded_without_usage["usage"]
    del recorded_without_usage["total_cost_usd"]
    fake_run(json.dumps(recorded_without_usage))
    usage_log_path = tmp_path / "llm_usage.jsonl"

    llm.ask("qa", "p", [], COLOR_SCHEMA, config=make_config(), usage_log_path=usage_log_path)

    entry = json.loads(usage_log_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["input_tokens"] is None
    assert entry["output_tokens"] is None
    assert entry["cache_read_tokens"] is None
    assert entry["cost_usd"] is None
