"""Test de garde ADR-49cd : clipper/web n'appelle qu'une liste fermée de fonctions
des modules d'étape (TASK-8fd1).

ADR-49cd autorise clipper/web/ à importer et utiliser SEULEMENT les symboles
ci-dessous des modules d'étape. Élargir cette liste = nouvel ADR, pas une
modification de ce test. L'analyse est statique (ast) : le source n'est jamais
exécuté.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

from clipper import pipeline

WEB_DIR = Path(__file__).resolve().parents[1] / "clipper" / "web"

# ADR-49cd : fonctions pures de validation / lecture de config autorisées dans
# clipper/web. Ne rien ajouter ici sans nouvel ADR.
ALLOWED = {
    "clipper.moments": frozenset({"resolve_rubric_path", "_BUILTIN_RUBRICS", "MomentsError"}),
    "clipper.reframe": frozenset({"_settings", "_letterbox_geometry", "ReframeError"}),
    "clipper.render": frozenset({"_settings", "check_cta_handle_gap", "RenderError"}),
}


# Motifs affichés dans un échec (Violation.why).
WHY_SYMBOLE = "symbole hors liste ADR-49cd"
WHY_MODULE = "module d'étape hors liste ADR-49cd"
WHY_DYNAMIQUE = "import dynamique hors liste ADR-49cd"


class Violation(NamedTuple):
    file: str
    line: int
    symbol: str
    why: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line} {self.symbol} ({self.why})"


STEP_MODULES = frozenset(f"clipper.{name}" for name in pipeline.STEPS)


def py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def scan_tree(root: Path) -> list[Violation]:
    found: list[Violation] = []
    for path in py_files(root):
        rel = path.relative_to(root).as_posix()
        found += scan_source(path.read_text(encoding="utf-8"), rel)
    return found


def _dotted(node: ast.Attribute) -> str | None:
    # « rf.run » -> "rf.run" ; None si la base n'est pas un nom simple (f(x).y).
    parts = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


# Chargements dynamiques de modules : leur premier argument doit être une
# constante hors module d'étape, sinon le scan ne peut pas savoir ce qui est chargé.
DYNAMIC_IMPORTS = frozenset({"importlib.import_module", "import_module", "__import__"})


def _dynamic_import_violations(arg: ast.expr, filename: str, line: int, call: str) -> list[Violation]:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        if arg.value in STEP_MODULES:
            return [Violation(filename, line, arg.value, WHY_MODULE)]
        return []
    return [Violation(filename, line, f"{call}(argument dynamique)", WHY_DYNAMIQUE)]


def _getattr_violations(node: ast.Call, filename: str, aliases: dict[str, str]) -> list[Violation]:
    # getattr(alias, "nom") sur un module d'étape ; getattr(clipper, "nom") pour un module d'étape.
    if len(node.args) < 2:
        return []
    base = node.args[0].id  # type: ignore[attr-defined]  # appelé seulement sur un Name
    attr = node.args[1]
    constant = attr.value if isinstance(attr, ast.Constant) and isinstance(attr.value, str) else None
    if base == "clipper" and base not in aliases:
        if constant is not None and f"clipper.{constant}" in STEP_MODULES:
            return [Violation(filename, node.lineno, f"clipper.{constant}", WHY_MODULE)]
        return []
    module = aliases.get(base)
    if module is None:
        return []
    if constant is None:
        return [Violation(filename, node.lineno, f"{module}.(dynamique)", WHY_SYMBOLE)]
    if module not in ALLOWED or constant not in ALLOWED[module]:
        return [Violation(filename, node.lineno, f"{module}.{constant}", WHY_SYMBOLE)]
    return []


def scan_source(source: str, filename: str = "<factice>") -> list[Violation]:
    tree = ast.parse(source, filename)
    found: list[Violation] = []
    # Nom local (tel qu'écrit dans le source) -> module d'étape complet.
    aliases: dict[str, str] = {}

    # Passe 1 : imports. Un module d'étape hors liste est signalé à l'import ;
    # un symbole hors liste d'un module autorisé l'est aussi, à sa ligne d'import.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in STEP_MODULES:
                    continue
                if a.name not in ALLOWED:
                    found.append(Violation(filename, node.lineno, a.name, WHY_MODULE))
                aliases[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in STEP_MODULES:
                if mod not in ALLOWED:
                    found.append(Violation(filename, node.lineno, mod, WHY_MODULE))
                    continue
                for a in node.names:
                    if a.name == "*" or a.name not in ALLOWED[mod]:
                        symbol = f"{mod}.{a.name}"
                        found.append(Violation(filename, node.lineno, symbol, WHY_SYMBOLE))
            elif mod == "clipper":
                for a in node.names:
                    full = f"clipper.{a.name}"
                    if full not in STEP_MODULES:
                        continue
                    if full not in ALLOWED:
                        found.append(Violation(filename, node.lineno, full, WHY_MODULE))
                    aliases[a.asname or a.name] = full

    # Passe 2 : attributs utilisés sur un module d'étape autorisé (alias.attr).
    # Les noms les plus longs d'abord : « clipper.reframe » avant « clipper ».
    keys = sorted(aliases, key=len, reverse=True)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        dotted = _dotted(node)
        if dotted is None:
            continue
        for key in keys:
            if dotted.startswith(key + "."):
                module = aliases[key]
                symbol = dotted[len(key) + 1:].split(".")[0]
                if module in ALLOWED and symbol not in ALLOWED[module]:
                    found.append(Violation(filename, node.lineno, f"{module}.{symbol}", WHY_SYMBOLE))
                break

    # Passe 3 : chargement dynamique. Un nom non constant ou une constante
    # désignant un module d'étape est signalé ; getattr et sys.modules aussi.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            name = _dotted(node.func) if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name in DYNAMIC_IMPORTS:
                found += _dynamic_import_violations(node.args[0], filename, node.lineno, name)
            elif name == "getattr" and isinstance(node.args[0], ast.Name):
                found += _getattr_violations(node, filename, aliases)
            elif name == "sys.modules.get":
                found += _dynamic_import_violations(node.args[0], filename, node.lineno, name)
        elif isinstance(node, ast.Subscript) and _dotted(node.value) == "sys.modules":
            found += _dynamic_import_violations(node.slice, filename, node.lineno, "sys.modules")

    # Un même appel peut apparaître sur plusieurs nœuds (a.b.c) : une seule ligne.
    unique = sorted(set(found), key=lambda v: (v.file, v.line, v.symbol))
    return unique


def _fmt(violations: list[Violation]) -> str:
    return "\n".join(str(v) for v in violations)


def test_clipper_web_appelle_seulement_la_liste_fermee():
    found = scan_tree(WEB_DIR)
    assert not found, "clipper/web appelle hors de la liste ADR-49cd :\n" + _fmt(found)


def test_le_scan_couvre_bien_app_py():
    # Garde contre un passage à vide : le scan doit réellement lire le paquet.
    names = {p.name for p in py_files(WEB_DIR)}
    assert {"app.py", "__init__.py"} <= names


def test_la_liste_couvre_les_etapes_de_pipeline():
    # La liste ne peut désigner que des modules d'étape réels (pipeline.STEPS).
    steps = {f"clipper.{name}" for name in pipeline.STEPS}
    assert set(ALLOWED) <= steps


def test_symbole_hors_liste_nomme_fichier_ligne_symbole():
    src = "from clipper import reframe as rf\n\nrf.run(config)\n"
    found = scan_source(src, "app.py")
    assert found == [Violation("app.py", 3, "clipper.reframe.run", WHY_SYMBOLE)]


def test_appel_reframe_run_dans_copie_du_source_est_detecte(tmp_path):
    # Sous-critère (3) : une copie temporaire d'app.py à laquelle on ajoute
    # un appel reframe.run doit échouer, sans toucher au vrai app.py.
    web = tmp_path / "web"
    web.mkdir()
    real = (WEB_DIR / "app.py").read_text(encoding="utf-8")
    (web / "app.py").write_text(real + "\n_fuite = reframe_mod.run\n", encoding="utf-8")
    found = scan_tree(web)
    last = len(real.splitlines()) + 2
    assert [(v.file, v.line, v.symbol) for v in found] == [("app.py", last, "clipper.reframe.run")], _fmt(found)


def test_import_de_module_d_etape_hors_liste_est_detecte():
    src = "import clipper.audio\nfrom clipper import scenes\n"
    found = scan_source(src, "x.py")
    assert [(v.line, v.symbol) for v in found] == [(1, "clipper.audio"), (2, "clipper.scenes")]


def test_from_import_de_symbole_interdit_est_detecte():
    src = "from clipper.render import _settings, render_video\n"
    found = scan_source(src, "x.py")
    assert [(v.line, v.symbol) for v in found] == [(1, "clipper.render.render_video")]


def test_star_import_de_module_d_etape_est_detecte():
    found = scan_source("from clipper.reframe import *\n", "x.py")
    assert [(v.line, v.symbol) for v in found] == [(1, "clipper.reframe.*")]


def test_alias_autorises_passent():
    src = (
        "from clipper import moments as moments_mod\n"
        "from clipper import reframe as reframe_mod\n"
        "import clipper.render as render_mod\n"
        "from clipper.render import RenderError\n"
        "moments_mod.resolve_rubric_path('x')\n"
        "reframe_mod._settings(config)\n"
        "reframe_mod._letterbox_geometry(1, 2, s)\n"
        "render_mod.check_cta_handle_gap(render_mod._settings(config))\n"
    )
    assert scan_source(src, "x.py") == []


def test_alias_interdits_sont_suivis():
    src = "import clipper.reframe as rf\nrf.run(config)\n"
    found = scan_source(src, "x.py")
    assert [(v.line, v.symbol) for v in found] == [(2, "clipper.reframe.run")]


def test_import_direct_puis_appel_nu_est_signale_a_l_import():
    src = "from clipper.reframe import run\nrun(config)\n"
    found = scan_source(src, "x.py")
    assert [(v.line, v.symbol) for v in found] == [(1, "clipper.reframe.run")]


def test_modules_hors_etapes_ne_sont_pas_contraints():
    # pipeline n'est pas un module d'étape : ses attributs ne sont pas dans la liste.
    src = "from clipper import pipeline\npipeline.run_video('x')\n"
    assert scan_source(src, "x.py") == []


def test_import_dynamique_a_nom_non_constant_est_detecte():
    src = 'import importlib\nimportlib.import_module(f"clipper.{x}")\n'
    found = scan_source(src, "x.py")
    assert [(v.line, v.why) for v in found] == [(2, WHY_DYNAMIQUE)]


def test_import_dynamique_de_module_hors_etapes_passe():
    src = 'import importlib\nimportlib.import_module("json")\n'
    assert scan_source(src, "x.py") == []


def test_import_dynamique_de_module_d_etape_constant_est_detecte():
    src = 'import importlib\nimportlib.import_module("clipper.subtitles")\n'
    found = scan_source(src, "x.py")
    assert [(v.line, v.symbol, v.why) for v in found] == [(2, "clipper.subtitles", WHY_MODULE)]


def test_dunder_import_dynamique_est_detecte():
    found = scan_source("mod = __import__(nom)\n", "x.py")
    assert [(v.line, v.why) for v in found] == [(1, WHY_DYNAMIQUE)]


def test_getattr_hors_liste_sur_alias_d_etape_est_detecte():
    src = "from clipper import reframe as rf\ngetattr(rf, 'run')\n"
    found = scan_source(src, "x.py")
    assert [(v.line, v.symbol) for v in found] == [(2, "clipper.reframe.run")]


def test_getattr_autorise_sur_alias_d_etape_passe():
    src = "from clipper import reframe as rf\ngetattr(rf, '_settings')\n"
    assert scan_source(src, "x.py") == []


def test_getattr_avec_nom_dynamique_sur_alias_d_etape_est_detecte():
    src = "from clipper import render as r\ngetattr(r, nom)\n"
    found = scan_source(src, "x.py")
    assert [(v.line, v.why) for v in found] == [(2, WHY_SYMBOLE)]


def test_getattr_sur_paquet_clipper_visant_une_etape_est_detecte():
    src = "import clipper\ngetattr(clipper, 'scenes')\n"
    found = scan_source(src, "x.py")
    assert [(v.line, v.symbol) for v in found] == [(2, "clipper.scenes")]


def test_sys_modules_visant_une_etape_est_detecte():
    src = "import sys\nsys.modules['clipper.scenes']\n"
    found = scan_source(src, "x.py")
    assert [(v.line, v.symbol) for v in found] == [(2, "clipper.scenes")]


def test_sys_modules_avec_nom_dynamique_est_detecte():
    src = "import sys\nsys.modules.get(nom)\n"
    found = scan_source(src, "x.py")
    assert [(v.line, v.why) for v in found] == [(2, WHY_DYNAMIQUE)]


def test_sys_modules_hors_etapes_passe():
    src = "import sys\nsys.modules['json']\n"
    assert scan_source(src, "x.py") == []
