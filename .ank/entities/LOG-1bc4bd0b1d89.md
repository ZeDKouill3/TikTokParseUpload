---
id: LOG-1bc4bd0b1d89
type: log
title: "Cause : target_fps = min(source_fps, max_fps) gardait la cadence source si < 30. Fix : target_fps ="
created: 2026-09-25T19:41:20Z
author: w-17b6
scope:
  - clipper/render.py
  - tests/test_render.py
about: TASK-17b644274e1f
seq: 2
schema: 4
version: 1
---

 max_fps toujours (source_fps/_probe_fps supprimes, plus utilises). Test ajoute : source synthetique 25fps -> sortie verifiee 30/1 via ffprobe. Suite complete verte (593 passed, 7 skipped).
