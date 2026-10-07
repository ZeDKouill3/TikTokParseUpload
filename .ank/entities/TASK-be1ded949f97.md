---
id: TASK-be1ded949f97
type: task
slug: release-v0-5-3-changelog-depuis-v0-5-2-version-p
title: "Release v0.5.3 : CHANGELOG depuis v0.5.2, version, plan de versions, badge README"
created: 2026-10-07T09:40:54Z
author: nicoc@zedk_ordi
status: done
scope:
  - CHANGELOG.md
  - pyproject.toml
  - clipper/__init__.py
  - README.md
  - docs/versions.md
  - tests/test_release_docs.py
blocked_by: []
done_criteria: |
  Préparer la pré-version 0.5.3 (jamais de tag/push/gh par le worker). CHANGELOG.md : la section [Non publié] devient [0.5.3] - <date Paris du jour>, COMPLÈTE depuis v0.5.2 (git log v0.5.2..HEAD + ank show des tâches : TASK-9d01, TASK-4e7c, TASK-26dc, TASK-8525, TASK-3274, TASK-e2a1), en français pour un utilisateur ; la section Sorties de jeux (IGDB) est annoncée telle que livrée (collecte par jeux triés par hypes, étiquette Portage) sans annoncer le calendrier en jaquettes ni le filtre de communauté Steam (TASK-82da/TASK-4944 pas encore fusionnées) ; nouvelle section [Non publié] vide au-dessus ; liens de comparaison mis à jour. Version 0.5.3 dans pyproject.toml et clipper/__init__.py ; README badge et mentions zip/wheel 0.5.2 -> 0.5.3 ; docs/versions.md ligne v0.5.3 (publiée). tests/test_release_docs.py vert. HORS dépôt : research/notes-v0.5.3.md = copie de la section [0.5.3]. Ne pas construire le zip.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/e1e27b28feb2@1b8da18
    tree: scope/cec5a2dfc11d
    criteria: df9392cab98b
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Demande utilisateur 2026-10-07 (« lance les 3 »). Modèle : TASK-2c31b7e1358c.
