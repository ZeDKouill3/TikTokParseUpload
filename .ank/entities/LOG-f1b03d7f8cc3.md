---
id: LOG-f1b03d7f8cc3
type: log
title: Mesures extrait réel 20 min (VOD v2894981843, h264 1080p60, t=3600-4800 s, 2 fenêtres de parole, PC
created: 2026-10-09T11:40:17Z
author: w-ce12e4753cfe
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
  - CHANGELOG.md
about: TASK-ce12e4753cfe
seq: 2
schema: 4
version: 1
---

 12 coeurs). Référence : 62,0 s / 63,5 s, 66 scènes. Décodage ffmpeg seul (300 s, fps=30, scale 256) : 16,3 s avec skip_loop_filter, 20,4 s sans, 14,6 s à 15 fps, 11,0 s -skip_frame noref ; le décodage sature déjà les 12 coeurs (~1150 img/s décodées), le détecteur Python n'est pas le goulot.
