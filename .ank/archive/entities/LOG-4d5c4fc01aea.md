---
id: LOG-4d5c4fc01aea
type: log
title: "released: Critère non tenable dans le scope : le jury en mode auto casse"
created: 2026-09-25T19:09:02Z
author: w-8e2f
scope:
  - clipper/moments.py
  - tests/test_moments.py
about: TASK-8e2f016d4599
seq: 4
schema: 4
version: 1
---

 tests/test_pipeline.py::test_auto_runs_every_step_queues_a_transient_error_then_finishes (son faux LLM refuse l'usage jury_retention), fichier hors scope. Implémentation complète et verte sur tests/test_moments.py (branche task/TASK-8e2f-moments-jury). À faire : ajouter tests/test_pipeline.py au scope (ou tâche préalable) pour que answer() réponde aux usages jury_* (chaque ref de l'enum, scores 9, veto false).
