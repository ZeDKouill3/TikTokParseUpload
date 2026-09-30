---
id: LOG-f824bc17fe2f
type: log
title: "released: Correctif xdist + cv2.setNumThreads(1) implemente et mesure (1166 passed/25 skipped"
created: 2026-09-30T19:34:34Z
author: w-42a46cb23f78
scope:
  - pyproject.toml
  - tests/conftest.py
about: TASK-42a46cb23f78
seq: 8
schema: 4
version: 1
---

 identique au baseline dans le run propre). ank done a neanmoins vu tests/test_qa.py::test_parallel_four_overlaps_llm_calls flaky sous charge CPU partagee (autres sessions actives sur la machine) : test de concurrence reelle hors scope (pyproject.toml, tests/conftest.py). Nouvelle tache TASK-c37fa74c63c8 creee pour le rendre robuste ; TASK-42a46cb23f78 bloque desormais sur elle.
