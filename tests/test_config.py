from __future__ import annotations

import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _install_fake_section_module(monkeypatch, name, config_defaults=None):
    """Install a fake clipper.<name> module in sys.modules, mirroring a real
    pipeline-step module that declares CONFIG_DEFAULTS for its own section."""
    module = types.ModuleType(f"clipper.{name}")
    if config_defaults is not None:
        module.CONFIG_DEFAULTS = config_defaults
    monkeypatch.setitem(sys.modules, f"clipper.{name}", module)
    return module


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


def test_config_example_documents_section_convention():
    text = (REPO_ROOT / "config.example.toml").read_text()

    assert "CONFIG_DEFAULTS" in text


def test_pyproject_discovers_clipper_subpackages():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    find_cfg = data["tool"]["setuptools"]["packages"]["find"]
    include = find_cfg["include"]

    assert "clipper" in include
    assert "clipper.*" in include


def test_pyproject_declares_yt_dlp_and_anthropic_dependencies():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    deps = data["project"]["dependencies"]

    assert any(d.split(">")[0].split("=")[0].strip() == "yt-dlp" for d in deps)
    assert any(d.split(">")[0].split("=")[0].strip() == "anthropic" for d in deps)


def test_config_section_merges_module_defaults_with_toml_table(isolated_cwd, monkeypatch):
    from clipper.config import load_config

    _install_fake_section_module(
        monkeypatch, "fake_step", config_defaults={"model": "small", "threshold": 0.5}
    )
    (isolated_cwd / "config.toml").write_text('[fake_step]\nmodel = "large"\n')

    config = load_config(isolated_cwd / "config.toml")

    assert config.section("fake_step") == {"model": "large", "threshold": 0.5}


def test_config_section_returns_only_defaults_when_table_absent(isolated_cwd, monkeypatch):
    from clipper.config import load_config

    _install_fake_section_module(
        monkeypatch, "fake_step", config_defaults={"model": "small", "threshold": 0.5}
    )

    config = load_config(isolated_cwd / "config.toml")

    assert config.section("fake_step") == {"model": "small", "threshold": 0.5}


def test_config_section_passes_nested_tables_unchanged(isolated_cwd, monkeypatch):
    from clipper.config import load_config

    _install_fake_section_module(
        monkeypatch, "fake_step", config_defaults={"model": "small", "extra": {}}
    )
    (isolated_cwd / "config.toml").write_text(
        '[fake_step]\nmodel = "large"\n[fake_step.extra]\nfoo = "bar"\n'
    )

    config = load_config(isolated_cwd / "config.toml")

    assert config.section("fake_step") == {"model": "large", "extra": {"foo": "bar"}}


def test_config_rejects_unknown_key_in_section(isolated_cwd, monkeypatch):
    from clipper.config import ConfigError, load_config

    _install_fake_section_module(monkeypatch, "fake_step", config_defaults={"model": "small"})
    (isolated_cwd / "config.toml").write_text('[fake_step]\nnot_a_real_key = 1\n')

    with pytest.raises(ConfigError):
        load_config(isolated_cwd / "config.toml")


def test_config_rejects_section_without_matching_module(isolated_cwd):
    from clipper.config import ConfigError, load_config

    (isolated_cwd / "config.toml").write_text('[no_such_clipper_module_xyz]\nfoo = 1\n')

    with pytest.raises(ConfigError):
        load_config(isolated_cwd / "config.toml")


def test_config_rejects_section_module_without_config_defaults(isolated_cwd, monkeypatch):
    from clipper.config import ConfigError, load_config

    _install_fake_section_module(monkeypatch, "fake_step_no_defaults", config_defaults=None)
    (isolated_cwd / "config.toml").write_text('[fake_step_no_defaults]\nfoo = 1\n')

    with pytest.raises(ConfigError):
        load_config(isolated_cwd / "config.toml")


def test_config_flat_keys_still_work_alongside_sections(isolated_cwd, monkeypatch):
    from clipper.config import load_config

    _install_fake_section_module(monkeypatch, "fake_step", config_defaults={"model": "small"})
    (isolated_cwd / "config.toml").write_text(
        'mode = "auto"\n[fake_step]\nmodel = "large"\n'
    )

    config = load_config(isolated_cwd / "config.toml")

    assert config.mode == "auto"
    assert config.section("fake_step") == {"model": "large"}
