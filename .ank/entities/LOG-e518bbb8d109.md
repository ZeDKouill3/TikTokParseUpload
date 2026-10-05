---
id: LOG-e518bbb8d109
type: log
title: PASSE REELLE (vrai Claude sonnet + vrai mediapipe, copies sous research/facecam-5745/, test marque
created: 2026-10-05T22:19:11Z
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
seq: 5
schema: 4
version: 1
---

 skipif CLIPPER_CLAUDE_INTEGRATION=1, 2 passed en 55 s) : v2887364910 -> periode 0 [0-958] aucun, periode 1 -> candidat 3 (cadre net 32,360 336x238, la webcam a casque en haut a gauche, que le visage ne trouvait que sur 7 % des images) ; v2888230655 -> periode 0 [0-1848, Just Chatting] aucun, periode 1 [1848-9663] -> candidat 4 (visage, 1426,418 436x310 = la webcam du jeu). COUT mesure (llm_usage.jsonl) : 0,0358 $ (2 appels) pour v2887364910, 0,0397 $ (2 appels) pour v2888230655 ; 7 a 11 s par appel. Sur Hctuan la periode 1 contient encore des pauses en grand visage (le Just Chatting revient plus tard) : elles restent dans la 2e periode, le candidat gagne a la majorite des images.
