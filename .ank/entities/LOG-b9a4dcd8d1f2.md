---
id: LOG-b9a4dcd8d1f2
type: log
title: "Rouge: 9 tests. Deja verts sans code: single 50 s rejete / 90 s retenu, multipart 10 min retenu,"
created: 2026-09-28T20:23:46Z
author: w-7758
scope:
  - rubric.toml
  - clipper/moments.py
  - tests/test_moments.py
  - tests/test_pipeline.py
about: TASK-7758e6074dc6
seq: 3
schema: 4
version: 1
---

 exploration qui evite un single chevauchant un passage retenu (overlap deja verifie contre kept). Piege test: bonus heatmap+pic audio pousse un passage WEAK (59.2) au-dessus de min_score -> passage LOW dans le test sous min_score.
