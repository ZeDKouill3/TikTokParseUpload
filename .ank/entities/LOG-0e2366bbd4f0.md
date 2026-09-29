---
id: LOG-0e2366bbd4f0
type: log
title: Mesure reelle (extrait 10 min AV1 1080p de ivl0nxa3C7o, copie hors depot, ffmpeg -ss 600 -t 600 -c
created: 2026-09-29T08:29:20Z
author: w-559adc7a1505
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
about: TASK-559adc7a1505
seq: 3
schema: 4
version: 1
---

 copy, CPU seul, hors depot workspace/output/) : detect_scenes total extract_parallel=1 -> 157.4s (143 scenes, 198 frames) ; extract_parallel=4 -> 74.8s (memes 143 scenes / 198 frames). Detection seule (_detect_scene_list, non affectee par le parallelisme) : 33.6s. Extraction donc ~123.8s (79% du total) en sequentiel vs ~41.2s (55% du total) en parallele x4, soit extraction ~3x plus rapide et total ~2.1x plus rapide.
