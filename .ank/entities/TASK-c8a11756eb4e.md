---
id: TASK-c8a11756eb4e
type: task
slug: wheel-autonome-grille-et-config-d-exemple-embarq
title: "Wheel autonome : grille et config d'exemple embarquées, commande clipper, 'clipper init'"
created: 2026-09-30T10:54:46Z
author: nicoc@zedk_ordi
status: open
scope:
  - pyproject.toml
  - clipper/__main__.py
  - clipper/moments.py
  - clipper/assets
  - tests/test_packaging.py
  - tests/test_cli_init.py
  - docs/releases/v0.1.0.md
  - README.md
  - docs/GUIDE.md
blocked_by: []
done_criteria: |
  Installée seule dans un venv neuf (uv venv + uv pip install dist/clipper-0.1.0-py3-none-any.whl, hors du dépôt), la wheel fournit : la commande 'clipper' ([project.scripts]) en plus de 'python -m clipper' ; la grille par défaut et config.example.toml embarquées (package data, ex. clipper/assets/rubric.toml, copie exacte de rubric.toml du dépôt, vérifiée par un test d'égalité) ; 'clipper init' qui écrit config.toml et rubric.toml dans le dossier courant (refuse d'écraser sans --force, erreur explicite) ; rubric_path par défaut résolu explicitement (valeur documentée, ex. 'builtin' -> grille embarquée ; un chemin donné est utilisé tel quel ; fichier absent = erreur explicite, jamais de repli silencieux, ADR-ad2e) ; test de packaging qui construit la wheel, l'installe dans un venv temporaire hors dépôt et lance 'clipper --help' et 'clipper init' (sauté si uv absent) ; README, GUIDE et docs/releases/v0.1.0.md : installation depuis la wheel = pip/uv install de la wheel puis 'clipper init' ; comportement dans le dépôt inchangé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Constat 2026-09-30 avant la release v0.1.0 (uv build) : la wheel ne contient que clipper/*.py, les polices et le web statique ; rubric.toml (lu via [moments] rubric_path = "rubric.toml", chemin relatif au dossier courant) et config.example.toml n'y sont pas, et il n'y a pas d'entrée [project.scripts]. Une installation depuis la wheel échoue donc dès l'étape moments (et load_config exige un config.toml). Un autre worker (TASK-8abc, sortie verbeuse) modifie aussi clipper/__main__.py et clipper/moments.py : changements minimaux dans ces fichiers pour limiter les conflits.
