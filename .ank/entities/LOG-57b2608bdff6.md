---
id: LOG-57b2608bdff6
type: log
title: "FIX: learning.write_veille_report expose clips_produced + processing (VOD dans state/queue.json),"
created: 2026-10-08T10:54:39Z
author: w-cc7ccc0f7e8c
scope:
  - clipper/veille.py
  - clipper/learning.py
  - tests/test_veille.py
  - tests/test_learning.py
  - CHANGELOG.md
about: TASK-cc7ccc0f7e8c
seq: 3
schema: 4
version: 1
---

 missing=processing distinct de no_clips, bilan recalcule a chaque passage run_if_due; veille._bilan_lines montre en traitement / clips_produits / clips_publies / vues inconnues. 11 tests rouges avant fix, 572 verts (learning, veille, worker). CHANGELOG ok.
