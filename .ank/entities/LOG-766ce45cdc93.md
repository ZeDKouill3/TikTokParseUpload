---
id: LOG-766ce45cdc93
type: log
title: "closed: pas un bug : clip d'exploration du jury (ADR-1cf0 point 4), sous le seuil avant ET après"
created: 2026-09-30T09:54:03Z
author: nicoc@zedk_ordi
scope:
  - clipper/moments.py
  - clipper/pipeline.py
  - tests/test_moments.py
  - tests/test_pipeline.py
about: TASK-6e434ac2f22c
seq: 6
schema: 4
version: 1
---

 vision, déjà couvert par test_exploration_takes_the_rejected_candidate_where_the_jury_disagrees_most et test_rescore_after_vision_keeps_the_exploration
