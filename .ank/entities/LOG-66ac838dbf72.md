---
id: LOG-66ac838dbf72
type: log
title: "Hypothese fps=1 refutee : qa rejette le clip (mecanique, probablement duree/black_screen instable a"
created: 2026-09-30T08:13:56Z
author: w-cde183a0041f
scope:
  - tests/test_pipeline.py
about: TASK-cde183a0041f
seq: 4
schema: 4
version: 1
---

 si peu d'images) ; en plus le gain fps=5->fps=1 est faible (21.87/15.17/14.66 a fps=5 vs 15.13/12.91/11.53 a fps=1, a peine 30% de mieux pour 5x moins d'images) : un cout fixe (spawn ffmpeg x3 dans qa, thread pools, PIL/overlay) domine desormais, pas le decodage par image. Retour a fps=5 (tous verts) ; re-profiler pour localiser le reste.
