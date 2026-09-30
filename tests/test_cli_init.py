"""TASK-c8a11756eb4e : 'clipper init' ecrit config.toml et rubric.toml dans
le dossier courant (refuse d'ecraser sans --force), et [moments] rubric_path
se resout explicitement ("builtin" -> grille embarquee, tout autre chemin
utilise tel quel, fichier absent = erreur explicite, ADR-ad2e)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipper.__main__ import main
from clipper.moments import MomentsError, load_rubric, resolve_rubric_path

ROOT = Path(__file__).resolve().parent.parent


def test_init_writes_config_and_rubric_in_cwd(isolated_cwd):
    assert main(["init"]) == 0

    assert (isolated_cwd / "config.toml").read_text(encoding="utf-8") == (
        ROOT / "config.example.toml"
    ).read_text(encoding="utf-8")
    assert (isolated_cwd / "rubric.toml").read_text(encoding="utf-8") == (
        ROOT / "rubric.toml"
    ).read_text(encoding="utf-8")


def test_init_refuses_to_overwrite_without_force(isolated_cwd, capsys):
    assert main(["init"]) == 0
    (isolated_cwd / "config.toml").write_text('mode = "auto"\n', encoding="utf-8")

    exit_code = main(["init"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "config.toml" in err
    # rien n'a ete ecrase : ni le fichier modifie, ni rubric.toml en trop.
    assert (isolated_cwd / "config.toml").read_text(encoding="utf-8") == 'mode = "auto"\n'


def test_init_force_overwrites_existing_files(isolated_cwd):
    assert main(["init"]) == 0
    (isolated_cwd / "config.toml").write_text('mode = "auto"\n', encoding="utf-8")

    assert main(["init", "--force"]) == 0

    assert (isolated_cwd / "config.toml").read_text(encoding="utf-8") == (
        ROOT / "config.example.toml"
    ).read_text(encoding="utf-8")


def test_resolve_rubric_path_builtin_matches_repo_rubric():
    resolved = resolve_rubric_path("builtin")

    assert resolved.read_text(encoding="utf-8") == (ROOT / "rubric.toml").read_text(encoding="utf-8")


def test_resolve_rubric_path_uses_a_given_path_as_is():
    assert resolve_rubric_path("rubric.toml") == Path("rubric.toml")
    assert resolve_rubric_path("some/other.toml") == Path("some/other.toml")


def test_resolve_rubric_path_missing_file_is_an_explicit_error(isolated_cwd):
    with pytest.raises(MomentsError, match="introuvable"):
        load_rubric(resolve_rubric_path("absent-xyz.toml"))
