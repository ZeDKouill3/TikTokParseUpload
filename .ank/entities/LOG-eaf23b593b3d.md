---
id: LOG-eaf23b593b3d
type: log
title: "diagnostic: prompt facecam donnait 'vu sur N image(s)' pour un cadre, sans presence de visage;"
created: 2026-10-08T10:03:45Z
author: w-495c0dda5727
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
  - CHANGELOG.md
about: TASK-495c0dda5727
seq: 2
schema: 4
version: 1
---

 face_support null pour cadre pur. Fix: face_support mesure par cadre, prompt 'aucun visage vu dedans', garde-fou _stable_face_instead (seuil facecam_face_stable_share 0.8). Tests rouges (5 echecs) puis verts.
