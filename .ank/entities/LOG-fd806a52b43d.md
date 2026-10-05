---
id: LOG-fd806a52b43d
type: log
title: "Scope elargi (ank amend) a tests/integration/test_smoke_real.py : tests/test_smoke_coverage.py"
created: 2026-10-05T22:38:55Z
author: w-57453bb1e834
scope:
  - clipper/reframe.py
  - clipper/qa.py
  - clipper/llm/__init__.py
  - tests/test_reframe.py
  - tests/test_qa.py
  - tests/test_llm.py
  - config.example.toml
  - clipper/assets/config.example.toml
  - tests/integration/test_smoke_real.py
about: TASK-57453bb1e834
seq: 8
schema: 4
version: 1
---

 exige un test de fumee pour tout usage llm.ask du pipeline (nouvel usage 'facecam'). Aussi corrige : commentaire d'aide de facecam_period_step (test_web : 1re phrase simple, sans TASK-/fonction()).
