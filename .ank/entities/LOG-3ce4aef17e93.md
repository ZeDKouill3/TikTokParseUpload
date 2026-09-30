---
id: LOG-3ce4aef17e93
type: log
title: "Verification sous contention artificielle : 16 process Python de calcul intensif (spin CPU, en plus"
created: 2026-09-30T19:54:17Z
author: w-42a46cb23f78
scope:
  - pyproject.toml
  - tests/conftest.py
  - tests/test_qa.py
  - tests/test_vision.py
  - tests/test_transcribe.py
about: TASK-42a46cb23f78
seq: 10
schema: 4
version: 1
---

 des sessions agent voisines actives sur cette machine partagee) lances en tache de fond, puis 6 executions repetees des 6 tests modifies (sans xdist, -o addopts=""). Nouveau code : 6/6 OK a chaque passage (6 runs = 36 executions de tests, 0 echec). Meme protocole sur l'ancien code (sleep fixe, restaure temporairement via git stash) : 1 echec sur 6 passages, exactement le meme test que celui vu par ank done (test_vision.py::test_parallel_defaults_to_four, assert 3 == 4) -- confirme que la cause etait bien le sleep fixe insuffisant sous CPU sursouscrit, et que le remplacement par threading.Event la corrige. Comparaison du cout reel (hors concurrence) : test_qa.py::test_parallel_one_never_overlaps_llm_calls prend ~9-12s avant ET apres le fix (ffmpeg reel via make_mp4 + analyse QA reelle des 4 clips, rien a voir avec le changement) : pas de regression de performance introduite par le fix de robustesse.
