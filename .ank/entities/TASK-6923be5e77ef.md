---
id: TASK-6923be5e77ef
type: task
slug: release-v0-4-2-changelog-complet-depuis-v0-4-1-v
title: "Release v0.4.2 : CHANGELOG complet depuis v0.4.1, version, plan de versions, badge README"
created: 2026-10-06T00:04:29Z
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
  Préparer la pré-version 0.4.2 (l'utilisateur tague et publie lui-même, jamais de tag/push/gh par le worker). CHANGELOG.md : la section [Non publié] devient [0.4.2] - <date Paris du jour> et elle est COMPLÈTE : relire git log v0.4.1..HEAD (merges + ank show des tâches) et y décrire en français, pour un utilisateur, chaque changement visible depuis v0.4.1 (ajouts, changements, corrections), une seule longue section (pas de fichier de notes séparé dans le repo) ; nouvelle section [Non publié] vide au-dessus ; liens de comparaison en bas mis à jour si le fichier en a. Version 0.4.2 dans pyproject.toml et clipper/__init__.py ; README : badge et mentions du zip/wheel 0.4.1 -> 0.4.2 ; docs/versions.md : ligne v0.4.2 (publiée) cohérente avec les autres. tests/test_release_docs.py vert (adapter seulement si un test fige l'ancienne version). Écrire aussi, HORS dépôt, research/notes-v0.4.2.md = copie du texte de la section [0.4.2] (corps de la release GitHub). Ne pas construire le zip (fait par l'orchestrateur).
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/370b2156a8b0@c3228d9
    tree: scope/aa19f64721ce
    criteria: 9c5ac6044eaf
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
