---
id: LOG-c86eb1b4714a
type: log
title: Rouge vu sur reframe (dests letterbox, sortie du cadre, letterbox_top) et render (cta_handle_gap
created: 2026-10-03T21:04:10Z
author: w-3be386611f39
scope:
  - clipper/web/**
  - clipper/reframe.py
  - clipper/render.py
  - clipper/subtitles.py
  - tests/test_web.py
  - tests/test_reframe.py
  - tests/test_render.py
  - tests/test_subtitles.py
about: TASK-3be386611f39
seq: 3
schema: 4
version: 1
---

 negatif). Vert des le 1er passage, comportement deja present : render place le titre dans text_zones.title quelle qu'elle soit, cta_handle_gap deplace l'encadre, subtitles suit text_zones.subtitles -> la propagation preset -> rendu passe entierement par reframe.
