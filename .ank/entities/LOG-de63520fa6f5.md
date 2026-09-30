---
id: LOG-de63520fa6f5
type: log
title: "Banc termine (pane herdr w1:p2H) : small VRAM pic 1393 MiB, large-v3-turbo 3291 MiB (> seuil 3,2 Go"
created: 2026-09-30T18:03:00Z
author: w-b6b731ad188a
scope:
  - docs/benchmarks/whisper-modeles.md
  - clipper/transcribe.py
  - tests/test_transcribe.py
  - config.example.toml
about: TASK-b6b731ad188a
seq: 3
schema: 4
version: 1
---

 du critere). Qualite : nette amelioration sur parole propre (7VaA8XUKrAY, hallucinations corrigees, 3x moins de corrections transcript_fix), mitigee/degradee sur stream de jeu (v2887271276, code-switching vers l'anglais). Decision : garder small par defaut, aucune des 2 conditions de bascule (VRAM marge + qualite generalisable) n'est remplie ensemble. Ecrit docs/benchmarks/whisper-modeles.md, renvoi ajoute dans config.example.toml. Aucun changement a clipper/transcribe.py (condition de bascule non remplie -> pas de nouveau test requis).
