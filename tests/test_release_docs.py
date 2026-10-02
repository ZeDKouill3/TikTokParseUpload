"""TASK-c60110ce236a : publication de la v0.2.0. Le fond rédactionnel se relit à
l'oeil ; ce fichier verifie mecaniquement ce qui peut l'etre : version du
paquet, structure Keep a Changelog, notes de version, plan de versions, absence
de noms reels."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
NOTES = ROOT / "docs" / "releases" / "v0.2.0.md"
VERSIONS = ROOT / "docs" / "versions.md"
REPO_URL = "https://github.com/ZeDKouill3/TikTokParseUpload"

# Identifiants, noms de personnes ou de chaines reels (research/, hors scope git) :
# ne doivent jamais fuiter dans un artefact versionne.
LEAKED_TOKENS = ("madajel", "7VaA8XUKrAY", "ivl0nxa3C7o", "ClaudeRandom", "nicoc", "C:\\Users")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _changelog_section(text: str, title_pattern: str) -> str:
    match = re.search(rf"^## {title_pattern}.*?$(.*?)(?=^## |^\[[^\]]+\]: |\Z)", text, re.S | re.M)
    assert match, f"section {title_pattern!r} absente de CHANGELOG.md"
    return match.group(1)


def test_package_version_is_0_2_0():
    data = tomllib.loads(_read(ROOT / "pyproject.toml"))
    assert data["project"]["version"] == "0.2.0"


def test_changelog_header_mentions_semantic_versioning():
    head = _read(CHANGELOG).split("## ", 1)[0]
    assert "versionnage sémantique" in head
    assert "docs/versions.md" in head
    assert "pas (encore)" not in head


def test_changelog_has_empty_unreleased_then_released_0_2_0():
    text = _read(CHANGELOG)
    headings = re.findall(r"^## (.+)$", text, re.M)
    assert headings[0] == "[Non publié]"
    assert re.fullmatch(r"\[0\.2\.0\] - \d{4}-\d{2}-\d{2}", headings[1])
    assert headings[2].startswith("[0.1.0]")
    assert _changelog_section(text, r"\[Non publié\]").strip() == ""


@pytest.mark.parametrize("section", ["Ajouté", "Modifié", "Corrigé", "Sécurité", "Retiré"])
def test_changelog_0_2_0_has_each_keep_a_changelog_section(section):
    body = _changelog_section(_read(CHANGELOG), r"\[0\.2\.0\]")
    block = re.search(rf"^### {section}$(.*?)(?=^### |\Z)", body, re.S | re.M)
    assert block, f"### {section} absente de [0.2.0]"
    assert block.group(1).strip(), f"### {section} vide"


def test_changelog_footer_links_compare_tags():
    text = _read(CHANGELOG)
    assert f"[Non publié]: {REPO_URL}/compare/v0.2.0...HEAD" in text
    assert f"[0.2.0]: {REPO_URL}/compare/v0.1.0...v0.2.0" in text
    assert f"[0.1.0]: {REPO_URL}/releases/tag/v0.1.0" in text


REQUIRED_NOTE_THEMES = [
    "Console web", "Chaînes", "Comptes et coffre", "Publication TikTok", "Statistiques TikTok",
    "Jury et grille gaming", "Worker et file", "Performances",
]


def test_release_notes_have_the_expected_structure():
    text = _read(NOTES)
    headings = re.findall(r"^#{1,3} (.+)$", text, re.M)
    for theme in REQUIRED_NOTE_THEMES:
        assert any(theme in h for h in headings), f"thème manquant : {theme}"
    for section in ("Points forts", "Mettre à jour depuis la 0.1.0", "Avertissements", "Limites connues", "Remerciements"):
        assert any(section in h for h in headings), f"section manquante : {section}"
    assert text.startswith("# clipper v0.2.0")


def test_release_notes_cover_the_upgrade_steps():
    text = _read(NOTES)
    for needle in (
        'uv pip install -e ".[test]"', "playwright", "keyring", "tomli-w", "tzdata",
        "presets/", "state/", "config.toml", "clipper browser login",
        "réseau non résidentiel", "cookies",
    ):
        assert needle in text, f"manque dans les notes : {needle}"


def test_release_notes_use_a_neutral_channel_example():
    assert "ma_chaine" in _read(NOTES)


@pytest.mark.parametrize("path", [CHANGELOG, NOTES, VERSIONS], ids=lambda p: p.name)
def test_release_docs_leak_no_real_identifier(path):
    text = _read(path)
    for token in LEAKED_TOKENS:
        assert token not in text, f"{token!r} dans {path.name}"


def test_versions_marks_0_2_0_published_with_its_content():
    text = _read(VERSIONS)
    row = next(line for line in text.splitlines() if line.startswith("| v0.2.0 "))
    assert row.rstrip().endswith("| publiée |")
    assert "maintenant" not in row
    # Ce que v0.3.0 annonçait est dans la 0.2.0 : la feuille de route ne le promet plus.
    v030 = next(line for line in text.splitlines() if line.startswith("| v0.3.0 "))
    assert "Publication pilotée depuis l'écran Publication" not in v030
