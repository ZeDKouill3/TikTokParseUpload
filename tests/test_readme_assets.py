"""TASK-44aae8fe7bc1 : README pro (logo, animations SVG, sections). Le
contenu redactionnel se lit a l'oeil ; ce fichier verifie mecaniquement les
clauses du critere qui peuvent l'etre : sections presentes, liens relatifs
valides, logo reference, badges, SVG valides sans <script>, animation CSS
pure (pas de JavaScript), duree de boucle 15-25 s, aucun identifiant reel ou
chemin perso, ordre des etapes du pipeline, lisibilite clair/sombre."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DEMO_TERMINAL_SVG = ROOT / "docs" / "assets" / "demo-terminal.svg"
PIPELINE_SVG = ROOT / "docs" / "assets" / "pipeline.svg"

REQUIRED_SECTIONS = [
    "Ce que ça fait",
    "Démo",
    "Points forts",
    "Installation",
    "Démarrage rapide",
    "Formats",
    "Preset par chaîne et CTA abonnement",
    "Modes review/auto",
    "Interface web",
    "Coûts et performances",
    "Configuration",
    "Documentation",
    "Développement",
    "Limites et feuille de route",
]

# Identifiants/chemins reels vus dans les journaux sources (research/, hors
# scope git) : ne doivent jamais fuiter dans un artefact versionne.
LEAKED_TOKENS = (
    "7VaA8XUKrAY",
    "WVjOSRFWm4c",
    "ivl0nxa3C7o",
    "2887271276",
    "madajel",
    "ClaudeRandom",
    "nicoc",
    "C:\\Users",
)

PIPELINE_STEPS = (
    "download", "transcribe", "scenes", "audio", "moments", "vision",
    "parts", "captions", "reframe", "subtitles", "render", "qa",
)


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _relative_link_targets(text: str) -> list[str]:
    targets = re.findall(r"\]\(([^)]+)\)", text)  # [texte](cible) et ![alt](cible)
    targets += re.findall(r'src="([^"]+)"', text)  # <img src="cible">
    cleaned = []
    for target in targets:
        target = target.split(" ", 1)[0].strip()
        if not target or target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        cleaned.append(target)
    return cleaned


def test_readme_has_all_required_sections():
    text = _readme_text()
    headings = re.findall(r"^#{1,3}\s+(.+)$", text, flags=re.MULTILINE)
    for section in REQUIRED_SECTIONS:
        assert any(section in heading for heading in headings), f"section manquante : {section}"


def test_readme_relative_links_point_to_existing_files():
    text = _readme_text()
    targets = _relative_link_targets(text)
    assert targets, "aucun lien relatif trouve dans README.md"
    for target in targets:
        resolved = (README.parent / target).resolve()
        assert resolved.exists(), f"lien mort dans README.md : {target}"


def test_readme_shows_the_project_logo():
    text = _readme_text()
    assert "logo.svg" in text
    assert any("logo.svg" in target for target in _relative_link_targets(text))


def test_readme_has_version_and_python_badges():
    text = _readme_text()
    assert "0.2.0" in text
    assert "3.11" in text


def test_readme_has_no_licence_badge_when_no_license_file_exists():
    assert not (ROOT / "LICENSE").exists()
    assert not (ROOT / "LICENSE.txt").exists()
    assert not (ROOT / "LICENSE.md").exists()
    text = _readme_text().lower()
    assert not re.search(r"badge/licen[sc]e", text)


def test_readme_marks_the_future_clip_gif_placeholder():
    text = _readme_text()
    assert "<!-- demo-clip.gif -->" in text


@pytest.mark.parametrize("svg_path", [DEMO_TERMINAL_SVG, PIPELINE_SVG], ids=["demo-terminal", "pipeline"])
def test_svg_is_valid_xml(svg_path):
    ET.parse(svg_path)


@pytest.mark.parametrize("svg_path", [DEMO_TERMINAL_SVG, PIPELINE_SVG], ids=["demo-terminal", "pipeline"])
def test_svg_has_no_script_tag(svg_path):
    text = svg_path.read_text(encoding="utf-8").lower()
    assert "<script" not in text


@pytest.mark.parametrize("svg_path", [DEMO_TERMINAL_SVG, PIPELINE_SVG], ids=["demo-terminal", "pipeline"])
def test_svg_has_no_leaked_real_identifier_or_personal_path(svg_path):
    text = svg_path.read_text(encoding="utf-8")
    for leaked in LEAKED_TOKENS:
        assert leaked not in text, f"{leaked!r} fuite dans {svg_path.name}"


def test_demo_terminal_svg_uses_css_keyframes():
    text = DEMO_TERMINAL_SVG.read_text(encoding="utf-8")
    assert "@keyframes" in text


def test_demo_terminal_svg_loop_duration_between_15_and_25_seconds():
    text = DEMO_TERMINAL_SVG.read_text(encoding="utf-8")
    durations = [float(d) for d in re.findall(r"animation(?:-duration)?:\s*(?:[A-Za-z][\w-]*\s+)?([\d.]+)s", text)]
    assert durations, "aucune duree d'animation CSS trouvee dans demo-terminal.svg"
    assert all(15.0 <= d <= 25.0 for d in durations), durations


def test_demo_terminal_svg_replays_the_real_pipeline_command():
    text = DEMO_TERMINAL_SVG.read_text(encoding="utf-8")
    assert "python -m clipper -v run" in text


def test_demo_terminal_svg_command_line_visible_without_animation():
    """Une capture statique (t=0, animation non jouee) ne doit pas etre vide :
    au minimum la ligne de commande a une opacite de base de 1, independante
    du @keyframes qui la revele."""
    text = DEMO_TERMINAL_SVG.read_text(encoding="utf-8")
    match = re.search(r'<text[^>]*class="[^"]*prompt[^"]*"[^>]*>', text)
    assert match, "aucune ligne de commande (classe prompt) trouvee"
    prompt_tag = match.group(0)
    assert re.search(r"opacity:\s*1\b", prompt_tag), (
        "la ligne de commande n'a pas d'opacite de base 1 : invisible si l'animation ne joue pas"
    )


def test_demo_terminal_svg_shows_the_step_sequence():
    text = DEMO_TERMINAL_SVG.read_text(encoding="utf-8")
    positions = [text.index(f"etape {step}") for step in PIPELINE_STEPS]
    assert positions == sorted(positions)


def test_pipeline_svg_shows_all_steps_in_order():
    text = PIPELINE_SVG.read_text(encoding="utf-8")
    positions = [text.index(f">{step}<") for step in PIPELINE_STEPS]
    assert positions == sorted(positions)


def test_pipeline_svg_shows_the_output_contract():
    text = PIPELINE_SVG.read_text(encoding="utf-8")
    assert "output/" in text and ".mp4" in text and ".json" in text


def test_pipeline_svg_readable_in_light_and_dark_github_theme():
    text = PIPELINE_SVG.read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in text
