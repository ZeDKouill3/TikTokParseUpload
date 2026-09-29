---
id: LOG-a04ae6d761cd
type: log
title: "Verification manuelle sur WVjOSRFWm4c (2326 images cles, workspace en lecture seule : scenes.json"
created: 2026-09-29T14:07:46Z
author: w-c7e682a88189
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
about: TASK-c7e682a88189
seq: 4
schema: 4
version: 1
---

 copie + junction vers frames/ dans un workspace scratch, facecam.json ecrit uniquement dans le scratch, supprime apres). Resultat : facecam {x:1534, y:131, w:200, h:142} dans une source 1920x1080 -> en haut a droite. share=93.4% (>= facecam_min_share=0.8), reason=null. Visage vu sur 2325/2326 images cles (avant le fix : 40/2326 sur l'image entiere seule). Duree CPU : ~184s pour 2326*5 appels detecteur (image entiere + 4 coins agrandis).
