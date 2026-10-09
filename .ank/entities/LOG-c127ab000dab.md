---
id: LOG-c127ab000dab
type: log
title: "rouge: tail 101-130 + 112-118 rejete +11.0 s (reproduit). vert apres fix: overlap = sent.start<end"
created: 2026-10-09T00:07:13Z
author: w-3007a9a0c2d5
scope:
  - clipper/moments.py
  - tests/test_moments_action.py
  - CHANGELOG.md
about: TASK-3007a9a0c2d5
seq: 2
schema: 4
version: 1
---

 and sent.end>start remplace straddling; hook inchange. test 'A seule' etait deja vert avant fix (A non mesuree, accroche = image) : temoin de non-regression, pas un rouge.
