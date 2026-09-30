---
id: LOG-bec137186b9e
type: log
title: "released: Fix + tests de regression commites (85e99f1), verifies verts en cible"
created: 2026-09-30T18:18:51Z
author: w-c49298a278a8
scope:
  - clipper/subtitles.py
  - tests/test_subtitles.py
about: TASK-c49298a278a8
seq: 4
schema: 4
version: 1
---

 (tests/test_subtitles.py : 83 passed, 1 skipped) et par controle reel (regeneration .ass clip 05 depuis le vrai transcript, silence desormais vide entre D et 'ACCORD, copie mise a jour dans research/madajel/silences/05.ass). Bloque uniquement sur 'ank done' : deux autres workers (TASK-22a989e81a23, TASK-b6b731ad188a) tournent en parallele avec des charges CPU/GPU lourdes (VAD/decode video, banc whisper) ; le verifier 'tests' (pytest -q complet) a d'abord timeout a 900s sous cette contention, puis le process relance a ete tue par le harness pour RAM systeme critique pendant l'idle (pas un echec de mon fix). A relancer 'ank done' quand la machine aura de la marge (ces claims expirent ~18:21Z et ~18:33Z).
