"""Journalisation de la consommation (TASK-68eb6f43765d) pour le backend
claude-cli specifiquement : extraction de usage/total_cost_usd depuis la
sortie de `claude -p --output-format json`."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import clipper.llm as llm
from clipper.config import Config
from clipper.llm import LLMError

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


# --------------------------------------------------------------------------
# cache_prefix : ignore par ce backend depuis TASK-b384 (voir sa docstring
# module -- TASK-2cbb avait pose un bloc cache_control explicite dessus,
# cause residuelle et intermittente d'un 400 "A maximum of 4 blocks with
# cache_control" hors de notre controle, mesuree via --debug api). Un appel
# jury (le seul a fournir cache_prefix) suit donc desormais exactement le
# meme chemin qu'un appel sans cache_prefix.
# --------------------------------------------------------------------------

PREFIX = "Bloc commun a tous les juges, identique octet pour octet. " * 5


def test_cache_prefix_is_ignored_stdin_stays_plain_text(fake_run):
    run = fake_run(json.dumps(RECORDED_CLAUDE_CLI_WITH_USAGE))

    llm.ask("jury_x", PREFIX + "Role specifique.", [], COLOR_SCHEMA, config=make_config(), cache_prefix=PREFIX)

    cmd = run.calls[0]["cmd"]
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert "--input-format" not in cmd
    assert "--verbose" not in cmd
    assert "cache_control" not in run.calls[0]["input"]
    assert run.calls[0]["input"].startswith(PREFIX)


def test_no_cache_prefix_keeps_the_plain_text_stdin_unchanged(fake_run):
    # Regression : un appel sans cache_prefix (le cas courant hors jury)
    # garde le comportement d'avant TASK-2cbb (stdin brut, --output-format json).
    run = fake_run(json.dumps(RECORDED_CLAUDE_CLI_WITH_USAGE))

    llm.ask("vision", "p", [], COLOR_SCHEMA, config=make_config())

    cmd = run.calls[0]["cmd"]
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert "--input-format" not in cmd
    assert run.calls[0]["input"].startswith("p")


def test_only_the_message_diverges_between_two_same_model_roles_flags_are_identical(fake_run):
    run = fake_run(json.dumps(RECORDED_CLAUDE_CLI_WITH_USAGE))

    llm.ask("jury_a", PREFIX + "Role A.", [], COLOR_SCHEMA, config=make_config(), cache_prefix=PREFIX)
    llm.ask("jury_b", PREFIX + "Role B.", [], COLOR_SCHEMA, config=make_config(), cache_prefix=PREFIX)

    cmd_a, cmd_b = run.calls[0]["cmd"], run.calls[1]["cmd"]
    assert cmd_a == cmd_b  # meme modele, meme schema : aucun flag ne diverge

    input_a, input_b = run.calls[0]["input"], run.calls[1]["input"]
    assert input_a != input_b  # le role divergent se voit dans le stdin
    assert input_a.startswith(PREFIX) and input_b.startswith(PREFIX)


def test_cache_prefix_must_be_an_actual_prefix_of_the_prompt(fake_run):
    fake_run(json.dumps(RECORDED_CLAUDE_CLI_WITH_USAGE))
    with pytest.raises(LLMError):
        llm.ask("jury_x", "autre chose", [], COLOR_SCHEMA, config=make_config(), cache_prefix=PREFIX)


def test_images_combined_with_cache_prefix_never_carry_a_cache_control_block(fake_run, tmp_path):
    # TASK-746c puis TASK-b384 : l'API refuse au-dela de 4 blocs
    # cache_control par message, et claude -p en pose deja pour son propre
    # compte (systeme, tour interne...) -- nos propres blocs restent donc au
    # minimum, desormais aucun (cache_prefix ignore par ce backend, voir sa
    # docstring), quelle que soit la combinaison (image(s) + cache_prefix
    # compris, meme si aucun usage actuel ne les combine).
    img = tmp_path / "f.jpg"
    img.write_bytes(b"\xff\xd8fake-jpeg-bytes")
    run = fake_run(json.dumps(RECORDED_CLAUDE_CLI_WITH_USAGE))

    llm.ask("vision_x", PREFIX + "Role vision.", [img], COLOR_SCHEMA, config=make_config(), cache_prefix=PREFIX)

    content = json.loads(run.calls[0]["input"])["message"]["content"]
    marked = [b for b in content if "cache_control" in b]
    assert len(marked) == 0, content
    assert [b["type"] for b in content] == ["image", "text"]


# --------------------------------------------------------------------------
# Integration reelle (optionnelle)
# CLIPPER_CLAUDE_INTEGRATION=1 pytest tests/test_llm_claude_cli.py -k integration
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CLIPPER_CLAUDE_INTEGRATION") != "1",
    reason="integration Claude : definir CLIPPER_CLAUDE_INTEGRATION=1 (consomme du quota)",
)
def test_integration_shared_prefix_calls_succeed_without_caching(tmp_path):
    # TASK-b384 : 2 "roles" d'un meme modele (comme 2 juges de clipper.jury)
    # avec le meme cache_prefix reussissent tous les deux (plus de 400
    # intermittent, voir la docstring du module) ; leur schema/systeme n'a
    # jamais ete envoye avant ce test (contrairement au smoke test reel, qui
    # reutilise les schemas du jury de production, deja chauds cote Claude
    # Code : voir ank log TASK-b384, cout jury pratiquement inchange la),
    # donc rien a relire du cache fournisseur des le premier appel.
    prefix = "Contexte commun de test, invariant entre les deux appels. " * 200
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    usage_log_path = tmp_path / "usage.jsonl"
    config = make_config()

    llm.ask(
        "cache_test", prefix + "Role A : reponds ok=true.", [], schema,
        config=config, cache_prefix=prefix, usage_log_path=usage_log_path,
    )
    llm.ask(
        "cache_test", prefix + "Role B : reponds ok=true.", [], schema,
        config=config, cache_prefix=prefix, usage_log_path=usage_log_path,
    )

    entries = [json.loads(line) for line in usage_log_path.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 2
    for entry in entries:
        assert not entry["cache_read_tokens"], entries  # None ou 0 : plus de bloc a relire
