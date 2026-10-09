---
id: LOG-934d4dcbd9ca
type: log
title: "red : 9 tests echouent (import dynamique, getattr, sys.modules, config doc) ; 10 negatifs passent"
created: 2026-10-09T01:45:36Z
author: w-60487c2ba67a
scope:
  - clipper/web/app.py
  - clipper/config.py
  - tests/test_web_adr_guard.py
  - tests/test_config.py
  - tests/test_web.py
  - CHANGELOG.md
about: TASK-60487c2ba67a
seq: 2
schema: 4
version: 1
---

 deja (garde contre sur-detection) ; lancer pytest avec -o addopts= (xdist absent du venv de test)
