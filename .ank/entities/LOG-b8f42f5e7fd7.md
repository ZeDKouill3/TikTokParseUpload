---
id: LOG-b8f42f5e7fd7
type: log
title: "jury_calibration: stats avec video_id+moment_id reliées directement, stats_metric défaut"
created: 2026-10-07T12:08:27Z
author: w-7136
scope:
  - clipper/learning.py
  - clipper/jury_calibration.py
  - clipper/worker.py
  - tests/test_learning.py
  - tests/test_jury_calibration.py
  - tests/test_worker.py
about: TASK-7136ef90f0b4
seq: 3
schema: 4
version: 1
---

 views_percentile, stats sans métrique -> ignored no_metric. Tests rouge->vert (3 nouveaux).
