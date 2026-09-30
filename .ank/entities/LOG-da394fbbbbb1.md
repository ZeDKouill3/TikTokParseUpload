---
id: LOG-da394fbbbbb1
type: log
title: "Ecrit research/whisper-banc/bench.py : compare small vs large-v3-turbo sur 2 extraits 10 min"
created: 2026-09-30T17:47:27Z
author: w-b6b731ad188a
scope:
  - docs/benchmarks/whisper-modeles.md
  - clipper/transcribe.py
  - tests/test_transcribe.py
  - config.example.toml
about: TASK-b6b731ad188a
seq: 2
schema: 4
version: 1
---

 (7VaA8XUKrAY 600-1200s, v2887271276 3000-3600s), VRAM 1Hz pendant le banc, 1 appel reel transcript_fix par modele (mots concatenes des 2 extraits, sans passer par clipper.transcribe.transcribe pour eviter le decoupage en tranches). Lance dans le pane herdr calcul w1:p2H.
