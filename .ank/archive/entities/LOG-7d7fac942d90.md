---
id: LOG-7d7fac942d90
type: log
title: black_screen devient une verification locale via ffmpeg blackdetect (CONFIG_DEFAULTS
created: 2026-09-28T17:30:21Z
author: w-2960
scope:
  - clipper/qa.py
  - tests/test_qa.py
about: TASK-2960bcbcc575
seq: 2
schema: 4
version: 1
---

 black_min_seconds/black_pixel_threshold/black_picture_ratio), retire du prompt/schema IA ; echec ffmpeg = QAError (ADR-ad2e). 5 tests ajoutes (fondu 0.4s non rejete, noir 1.5s rejete, sans noir rien, seuil configurable, echec ffmpeg), 2 tests existants adaptes (black_screen n'est plus un type IA valide). Suite complete : 623 passed, 8 skipped.
