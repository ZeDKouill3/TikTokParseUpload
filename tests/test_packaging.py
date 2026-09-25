"""TASK-5d43 : dependances web (FastAPI, uvicorn, httpx) et donnees du
paquet (polices sous clipper/assets/**) declarees dans pyproject.toml."""

from __future__ import annotations

import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _load_pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_fastapi_and_uvicorn_are_project_dependencies():
    deps = _load_pyproject()["project"]["dependencies"]
    assert "fastapi" in deps
    assert "uvicorn" in deps


def test_httpx_is_in_the_test_extra():
    test_extra = _load_pyproject()["project"]["optional-dependencies"]["test"]
    assert "httpx" in test_extra


def test_opencv_override_is_preserved():
    """Le contournement single-OpenCV (mediapipe/scenedetect) ne doit pas
    disparaitre quand on ajoute les dependances web."""
    override = _load_pyproject()["tool"]["uv"]["override-dependencies"]
    assert override == ["opencv-python; sys_platform == 'never'"]


def test_import_fastapi_uvicorn_httpx():
    import fastapi  # noqa: F401
    import httpx  # noqa: F401
    import uvicorn  # noqa: F401


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv absent du PATH")
def test_wheel_contains_the_font_assets(tmp_path):
    """Une installation non editable (uv pip install .) doit apporter
    clipper/assets/fonts/Poppins-ExtraBold.ttf : on construit le wheel hors
    ligne (cache uv local, aucun reseau) dans une copie isolee du paquet
    (setuptools ecrit un dossier build/ a cote du pyproject.toml construit,
    qu'on ne veut pas laisser trainer dans le worktree) et on inspecte le
    contenu du wheel produit."""
    src = tmp_path / "src"
    shutil.copytree(ROOT / "clipper", src / "clipper")
    shutil.copy2(PYPROJECT, src / "pyproject.toml")

    out_dir = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--offline", "--wheel", "--out-dir", str(out_dir), str(src)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    wheels = list(out_dir.glob("*.whl"))
    assert wheels, f"aucun wheel produit dans {out_dir}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    assert "clipper/assets/fonts/Poppins-ExtraBold.ttf" in names
    assert "clipper/assets/fonts/OFL.txt" in names
