---
id: LOG-43ad05a40ac2
type: log
title: "released: httpx2 resolu (bien vu) : suite complete tourne, 736 passed/8 skipped, un seul echec"
created: 2026-09-28T19:36:23Z
author: w-ea6e
scope:
  - clipper/render.py
  - tests/test_render.py
  - clipper/subtitles.py
  - tests/test_subtitles.py
about: TASK-ea6e5b473075
seq: 6
schema: 4
version: 1
---

 REEL, cause par le changement ratifie de cette tache : tests/test_pipeline.py:679 (test_letterbox_plan_gives_its_subtitles_text_zone_to_subtitles) attend MarginV = y0 (+pas), or letterbox_offset_y=28 decale desormais MarginV a y0+28 (+pas) -- comportement voulu par done_criteria. Ce fichier est hors scope de TASK-ea6e (render.py/subtitles.py + leurs tests). Besoin d'une decision : autoriser une retouche d'une ligne d'assertion dans tests/test_pipeline.py (+ son commentaire), ou la faire faire ailleurs, avant de pouvoir clore via ank done.
