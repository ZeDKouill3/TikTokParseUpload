---
id: LOG-4b1124ae6db2
type: log
title: "Vert : 605 passed. Verif donnees reelles clip 00 (copie scratch) : m'a/d'autrui/t'as groupes ;"
created: 2026-09-25T19:45:54Z
author: w-29cf
scope:
  - clipper/subtitles.py
  - clipper/pipeline.py
  - tests/test_subtitles.py
  - tests/test_pipeline.py
about: TASK-29cfe8ff51a1
seq: 3
schema: 4
version: 1
---

 plans sans visage genant -> tiers inferieur (bas 1497 px) ; plan 0 (split, visages en double + fausse detection, cf TASK-b41f) sans position libre -> moins recouvrante (32 px) + warning journalise ; accroche 100..196 px jamais recouverte. Test apostrophes d'abord vert par hasard (4 jetons tombaient juste) : donnees refaites sur le cas reel 'Donc deja il m'a', rouge puis vert.
