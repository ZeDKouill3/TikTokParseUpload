"""TASK-8bf6 : verifie mecaniquement (AST sur le code reel des etapes, pas
une recopie a la main) que tests/integration/test_smoke_real.py::USAGES
couvre bien tous les usages LLM presents dans le pipeline (ADR-b16b).

N'utilise ni reseau ni backend LLM reel : lit le code source des modules et
importe clipper.jury pour sa table de juges (CONFIG_DEFAULTS, pas de
FakeBackend necessaire, aucun appel n'est fait)."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Modules d'etape (ADR-b16b) atteignables depuis clipper.pipeline qui font
# au moins un appel llm.ask direct. clipper.jury est aussi une etape du
# pipeline (appelee depuis moments.py) mais ses usages sont dynamiques
# (une table de juges, pas un litteral) : traites a part par _jury_usages.
PIPELINE_STEP_MODULES = (
    "transcribe", "moments", "vision", "parts", "captions", "reframe",
    "subtitles", "qa",
)


def _literal_llm_ask_usages(module_name: str) -> set[str]:
    """Les usages passes en 1er argument litteral de llm.ask() dans
    clipper/<module_name>.py."""
    source = (REPO_ROOT / "clipper" / f"{module_name}.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename=module_name)
    usages: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "ask"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "llm"
        ):
            continue
        if not node.args:
            raise AssertionError(f"clipper/{module_name}.py : llm.ask() sans usage positionnel")
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            raise AssertionError(
                f"clipper/{module_name}.py, ligne {node.lineno} : usage llm.ask non litteral -- "
                "ajoute une resolution dediee dans tests/test_smoke_coverage.py (comme _jury_usages "
                "pour clipper.jury)"
            )
        usages.add(first.value)
    return usages


def _jury_usages() -> set[str]:
    from clipper import jury

    judges = jury.CONFIG_DEFAULTS["judges"]
    return {entry.get("usage", f"jury_{name}") for name, entry in judges.items()}


def all_pipeline_llm_usages() -> set[str]:
    """Tous les usages LLM du pipeline, tels qu'ils apparaissent reellement
    dans le code des etapes -- jamais une liste recopiee a la main."""
    usages = _jury_usages()
    for module_name in PIPELINE_STEP_MODULES:
        usages |= _literal_llm_ask_usages(module_name)
    return usages


def _load_smoke_real():
    path = REPO_ROOT / "tests" / "integration" / "test_smoke_real.py"
    spec = importlib.util.spec_from_file_location("_smoke_real_for_coverage", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_real_usage_list_covers_every_pipeline_llm_usage() -> None:
    smoke_real = _load_smoke_real()
    tested = set(smoke_real.USAGES)
    expected = all_pipeline_llm_usages()
    missing = expected - tested
    extra = tested - expected
    assert not missing, f"usage(s) LLM du pipeline sans test de fumee : {sorted(missing)}"
    assert not extra, f"test de fumee pour un usage qui n'existe plus dans le pipeline : {sorted(extra)}"
