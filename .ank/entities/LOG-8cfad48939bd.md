---
id: LOG-8cfad48939bd
type: log
title: "Fix: reframe._clip_facecam exige un visage dans le rect (facecam_clip_face_min_share 0.5) quand"
created: 2026-10-08T08:13:56Z
author: w-9957d31c11a8
scope:
  - clipper/reframe.py
  - clipper/qa.py
  - tests/test_reframe.py
  - tests/test_qa.py
  - CHANGELOG.md
about: TASK-9957d31c11a8
seq: 3
schema: 4
version: 1
---

 edge_reason non nul ; qa.py defaut bloquant empty_webcam (stream_split seulement). Tests rouges avant fix (4 failed reframe, 2 qa), verts apres.
