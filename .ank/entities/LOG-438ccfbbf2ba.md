---
id: LOG-438ccfbbf2ba
type: log
title: "reframe: detect_facecam reecrit en periodes (grand visage plein ecran -> jeu, bisect a l'image"
created: 2026-10-05T21:58:47Z
author: w-57453bb1e834
scope:
  - clipper/reframe.py
  - clipper/qa.py
  - clipper/llm/__init__.py
  - tests/test_reframe.py
  - tests/test_qa.py
  - tests/test_llm.py
  - config.example.toml
  - clipper/assets/config.example.toml
about: TASK-57453bb1e834
seq: 2
schema: 4
version: 1
---

 cle), candidats locaux (visages + cadres nets en mouvement), planche numerotee, usage llm 'facecam' (schema webcam/reason, check numero connu), choix par clip sur la periode du debut, facecam_decision ecrit. Tests reframe verts. Reste: mesure reelle des 2 VOD, seuil QA, llm usages, config.example, spec successeur, test reel optionnel.
