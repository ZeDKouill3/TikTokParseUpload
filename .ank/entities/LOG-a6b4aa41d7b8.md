---
id: LOG-a6b4aa41d7b8
type: log
title: "released: Code et tests captions faits et verts (commit sur la branche), mais ank done échoue : 10"
created: 2026-10-05T20:30:50Z
author: w-35a1814125b6
scope:
  - clipper/captions.py
  - tests/test_captions.py
about: TASK-35a1814125b6
seq: 2
schema: 4
version: 1
---

 tests hors scope (test_browser/test_tiktok/test_youtube) échouent car la garde IP du navigateur (merge 08e4846) interroge la vraie IP publique, ici Royaume-Uni (attendu France) : BrowserError 'IP en Royaume-Uni'. Environnemental, pas lié à captions ; à rejouer sur réseau France ou en isolant ce test.
