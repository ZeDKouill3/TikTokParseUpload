---
id: TASK-08ce3b3cbe7f
type: task
slug: config-par-sections-d-clar-es-par-module-pyproje
title: Config par sections déclarées par module + pyproject prêt pour les étapes
created: 2026-09-25T10:30:06Z
author: UP60041549@wl0023729
status: done
scope:
  - clipper/config.py
  - config.example.toml
  - pyproject.toml
  - tests/test_config.py
blocked_by: []
done_criteria: |
  Une table [x] de config.toml est validée contre le dict CONFIG_DEFAULTS du module clipper.x (importé à la demande par clipper.config, sans liste centrale) : clé inconnue dans la section refusée (ConfigError), section sans module clipper.x ou sans CONFIG_DEFAULTS refusée, clés de premier niveau hors section toujours refusées ; Config.section('x') renvoie CONFIG_DEFAULTS fusionné avec la table (les défauts seuls si la table est absente), les valeurs imbriquées (tables sous [x]) sont passées telles quelles au module ; les clés à plat existantes (mode, workspace_dir, output_dir) et leurs tests restent inchangés ; testé avec un module factice ; config.example.toml explique qu'une section [x] se documente dans CONFIG_DEFAULTS de clipper.x ; pyproject.toml découvre les sous-paquets (clipper.llm s'installe) et déclare yt-dlp et anthropic en dépendances ; 'python -m pytest -q' passe.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/0646fdc25957@11098a0
    tree: scope/0c8b1b99b9de
    criteria: 9b3b55d234cb
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Ajoutée par l'orchestrateur (2026-09-25) : la config du squelette est plate et fermée, donc TASK-1557 (chemin du journal), TASK-4ca0 (cookies) et TASK-e492 (backend par usage) auraient toutes modifié config.py, config.example.toml et pyproject.toml, et n'auraient pas pu tourner en parallèle. Avec cette tâche, chaque étape ne touche que son propre module (CONFIG_DEFAULTS), et les trois tournent en même temps. Décision humaine : tâche préalable plutôt que série.
