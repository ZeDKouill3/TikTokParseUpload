---
id: LOG-38bec4ba7aa7
type: log
title: "Mesure plan 0 (683.3-689.56, mediapipe reel, tiles [1,2]) : visage reel detecte 31/31 images en"
created: 2026-09-25T19:35:44Z
author: w-b41f
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
about: TASK-b41fd515af38
seq: 2
schema: 4
version: 1
---

 grille 1 ET grille 2, boites IoU~0.7, NMS 0.3 les fusionne deja (1 boite gardee). Pistes #0/#1 = une seule fausse detection (torse ~x340 y460 taille 420-560, score 0.50-0.66, grille 2 seulement) presente 17/31 images, trous jusqu'a 8 images (684.81->686.43) > max_gap 5 : _build_tracks la coupe en 2 pistes. Visage retenu #2 (x519-846 marge -> 608 de large) + boite torse 700 px de large avec marge qui le chevauche en x : single infaisable, split avec fenetre 1215x1080 = quasi plan entier.
