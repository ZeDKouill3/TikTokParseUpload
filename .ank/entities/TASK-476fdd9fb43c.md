---
id: TASK-476fdd9fb43c
type: task
slug: squelette-clipper-config-workspace-en-cache-devi
title: "Squelette clipper : config, workspace en cache, device GPU, CLI"
created: 2026-09-25T09:39:34Z
author: claude-plan
status: done
scope:
  - pyproject.toml
  - .gitignore
  - config.example.toml
  - clipper/__init__.py
  - clipper/__main__.py
  - clipper/config.py
  - clipper/workspace.py
  - clipper/gpu.py
  - clipper/pipeline.py
  - tests/conftest.py
  - tests/test_config.py
  - tests/test_workspace.py
  - tests/test_gpu.py
blocked_by: []
done_criteria: |
  pyproject.toml déclare le paquet clipper (requires-python >= 3.11) et ses extras de test ; 'python -m clipper --help' sort en code 0 ; clipper.config charge config.toml (défauts documentés dans config.example.toml, dont mode review|auto) et refuse une clé inconnue ; clipper.workspace fournit pour un video_id le dossier workspace/<video_id>/, sait dire si une étape est faite et saute une étape déjà faite sauf force=True (testé) ; clipper.gpu renvoie cuda si torch.cuda est disponible sinon cpu, avec compute_type adapté (testé en simulant les deux cas) ; workspace/ et output/ sont dans .gitignore ; 'python -m pytest -q' passe sans GPU ni réseau.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/b77d2c673931@ec791ef
    tree: scope/a06bb4cb542b
    criteria: 1dafa541aff4
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Fondation de ADR-b16b71007578 et ADR-fb9bcb1e98f5. clipper/pipeline.py n'est ici qu'un registre d'étapes + la logique 'étape faite, on saute' ; l'orchestration complète est une tâche à part. Python 3.11+ : sur le PC de dev, créer un env (miniconda est installé).
