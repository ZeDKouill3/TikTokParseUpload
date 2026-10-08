---
id: LOG-560b6ebc92c2
type: log
title: "released: Critère (2) exige la clé retention dans GET /api/learning ; tests/test_web.py:9339 fige"
created: 2026-10-08T22:32:01Z
author: w-58d6dbbf1687
scope:
  - clipper/learning.py
  - clipper/web/static/screens/stats.js
  - tests/test_learning.py
  - CHANGELOG.md
about: TASK-58d6dbbf1687
seq: 6
schema: 4
version: 1
---

 l'ensemble exact des clés et casse (1 test). Ce fichier est hors scope (learning.py, stats.js, tests/test_learning.py, CHANGELOG). Décision à prendre : élargir le scope à tests/test_web.py (ajouter 'retention' à l'ensemble attendu) ou autoriser ce changement. Code et tests test_learning (90 verts) prêts dans le worktree, non commités.
