---
id: LOG-e235b1f6bf07
type: log
title: "Rouge : 2 échecs attendus (sans-source ; idempotence). Vert après _moment_source : clause 1 OK."
created: 2026-10-09T01:03:18Z
author: w-a97d3422e4a4
scope:
  - clipper/learning.py
  - tests/test_learning.py
  - CHANGELOG.md
about: TASK-a97d3422e4a4
seq: 3
schema: 4
version: 1
---

 Test idempotence déjà vert par construction (outcomes._append ne réécrit pas) : noté. Ancien test null-sans-source remplacé (il encodait le bug).
