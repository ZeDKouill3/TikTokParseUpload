---
id: LOG-2de2f46c747b
type: log
title: Verif manuelle WVjOSRFWm4c (workspace source en lecture seule, copie scratch avec jonction NTFS
created: 2026-09-29T23:03:34Z
author: w-493f184c4ce1
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
about: TASK-493f184c4ce1
seq: 3
schema: 4
version: 1
---

 vers frames/ pour eviter toute copie/ecriture sur l'original) : detect_facecam(force=True) avec facecam_max_keyframes=200 (defaut) -> 200/2326 images cles examinees, 39.7 s (etait 248 s, ~6.2x), rectangle facecam identique au px pres {x:1394,y:4,w:526,h:374} (share 0.92 vs 0.934 avant, meme decision). Suite pytest complete : 962 passed, 8 skipped, 1 echec (tests/test_vision.py::test_parallel_defaults_to_four, hors perimetre, timing de concurrence flaky -- repasse au vert seul en isolation x2) ; tests/test_reframe.py integralement vert (93 passed, 1 skipped).
