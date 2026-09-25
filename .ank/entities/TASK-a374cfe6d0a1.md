---
id: TASK-a374cfe6d0a1
type: task
slug: journal-des-r-sultats-par-clip-v-rit-terrain-du
title: Journal des résultats par clip (vérité terrain du jury)
created: 2026-09-25T18:38:16Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/outcomes.py
  - tests/test_outcomes.py
blocked_by: [TASK-5c16c59954ca]
done_criteria: |
  clipper.outcomes (bibliothèque) enregistre par clip, dans un journal append-only sous state/ (défaut state/outcomes.jsonl, réglage), des résultats reliés à la trace du jury (video_id, clip_id, moment_id) : verdict et défauts qa, décision humaine éventuelle, et statistiques de plateforme importées d'un fichier CSV (colonnes documentées : clip_id, vues, rétention 3 s, visionnage complet, partages, date) en attendant l'upload ; lecture filtrée par période ; aucun réseau ; tests sur tmp_path ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Met en œuvre le point 1 de ADR-1cf0 (proposé).
