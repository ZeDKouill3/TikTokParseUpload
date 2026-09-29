---
id: LOG-51ed4b1c0a76
type: log
title: "clauses: C1 facecam.json (90%->rect, 50%->absence, <1/4 image, detecteur via gpu, ferme) ; C2 choix"
created: 2026-09-29T10:02:35Z
author: cloud-9e0c
scope:
  - clipper/reframe.py
  - clipper/render.py
  - clipper/pipeline.py
  - clipper/qa.py
  - tests/test_reframe.py
  - tests/test_render.py
  - tests/test_pipeline.py
  - tests/test_qa.py
about: TASK-9e0c3278903b
seq: 1
schema: 4
version: 1
---

 par clip 85%->stream 60%->letterbox, plan unique fige ; C3 rendu 1080x1920 deux zones + sidecar layout stream ; C4 pipeline zone sous-titres ; C5 qa stream ; C6 absence -> letterbox + raison journalisee ; activation [reframe] layout = letterbox|stream_auto. Lecture : rectangle facecam = cadre au format du panneau centre sur le visage stable (stream_face_height), jeu = plus grande fenetre au format du panneau qui evite la facecam (+ marge), la plus centree.
