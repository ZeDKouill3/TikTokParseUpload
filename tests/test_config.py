from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_declares_clipper_package_for_py311_with_test_extra():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert data["project"]["name"] == "clipper"
    assert data["project"]["requires-python"] == ">=3.11"
    assert "test" in data["project"]["optional-dependencies"]


def test_cli_help_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "clipper", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0


def test_config_defaults_to_review_mode_when_no_config_file(isolated_cwd):
    from clipper.config import load_config

    config = load_config(isolated_cwd / "config.toml")

    assert config.mode == "review"


def test_config_loads_mode_auto_from_toml_file(isolated_cwd):
    from clipper.config import load_config

    (isolated_cwd / "config.toml").write_text('mode = "auto"\n')

    config = load_config(isolated_cwd / "config.toml")

    assert config.mode == "auto"


def test_config_rejects_unknown_key(isolated_cwd):
    from clipper.config import ConfigError, load_config

    (isolated_cwd / "config.toml").write_text('mode = "review"\nnot_a_real_key = 1\n')

    with pytest.raises(ConfigError):
        load_config(isolated_cwd / "config.toml")


def test_config_example_documents_the_defaults():
    from clipper.config import load_config

    config = load_config(REPO_ROOT / "config.example.toml")

    assert config.mode == "review"
