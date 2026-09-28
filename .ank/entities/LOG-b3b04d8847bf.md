---
id: LOG-b3b04d8847bf
type: log
title: "Fix: paliers par image dans _Geometry.follow (tiers) pour single : marges fit_margins [0.1,0.05,0]"
created: 2026-09-28T17:09:08Z
author: w-05b4
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
about: TASK-05b44079fae5
seq: 3
schema: 4
version: 1
---

 sur la zone balayee, boite instantanee, rognage lateral max_side_crop 0.2 centre, puis pour un visage suivi non retenu suivi sans exigence ; autres visages retenus toujours face_margin + zone balayee. Rejeu reel (memes detections) : 10 des 11 plans fallback_blur passent en single (00/1 03/2 06/2 07/2 10/3 retenus : paliers marge 0.1 a marge 0 zone balayee, 02/6 non retenu 625 px : rognage ; 01/2 02/3 03/7 04/3 non retenus). Reste 02/5 (LLM face=None, visage retenu 765 px, aucun palier : hors critere). Les 3 split restent split (deux visages retenus inevitablement coupes en single). Tests: 10 nouveaux rouges avant fix, 54 passed apres.
