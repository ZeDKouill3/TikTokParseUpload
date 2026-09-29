---
id: LOG-81ae914ebb1d
type: log
title: "pipeline.subtitles: ThreadPoolExecutor(max_workers=parallel) sur _subtitles_clip"
created: 2026-09-29T08:20:30Z
author: w-ce6e99b3e380
scope:
  - clipper/pipeline.py
  - clipper/subtitles.py
  - tests/test_pipeline.py
  - tests/test_subtitles.py
about: TASK-ce6e99b3e380
seq: 2
schema: 4
version: 1
---

 (plan+zones+generate par clip, dans le worker); toutes les futures vont au bout puis la 1re erreur (ordre des clips) remonte. parallel lu dans config.section('subtitles'), refusé si non entier ou < 1 (PipelineError). Tests dans test_pipeline.py: pic d'appels simultanés, identité 1 vs 4 (letterbox + 1 clip recadré), échec clip 03 avec autres écrits, relance qui saute les écrits, parallel 0/-2 refusé.
