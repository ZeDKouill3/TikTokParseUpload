---
id: LOG-95befb1b4505
type: log
title: "httpx2 confirme resolu (venv en tete de PATH) : collecte complete OK, 736 passed / 8 skipped. Un"
created: 2026-09-28T19:36:14Z
author: w-ea6e
scope:
  - clipper/render.py
  - tests/test_render.py
  - clipper/subtitles.py
  - tests/test_subtitles.py
about: TASK-ea6e5b473075
seq: 5
schema: 4
version: 1
---

 seul echec, reel et cause par mon changement : tests/test_pipeline.py::test_letterbox_plan_gives_its_subtitles_text_zone_to_subtitles (ligne 679) attend MarginV in (1300, 1300+78) = (y0, y0+pas) ; avec letterbox_offset_y=28 (ratifie par le critere de cette tache), MarginV vaut desormais y0+28 (+pas) = (1328, 1406). C'est un test d'integration pipeline->subtitles hors scope (clipper/pipeline.py n'est pas touche, seule l'assertion figee sur l'ancienne formule de MarginV est perimee). Hors perimetre autorise (render.py/subtitles.py + leurs tests seulement) : je ne le corrige pas sans autorisation explicite. Release pour arbitrage.
