---
id: LOG-21fcdd418bfb
type: log
title: "Reproduction (scratchpad/repro.py, python -I): transcript 3 segments sans words -> split_sentences"
created: 2026-10-10T10:06:15Z
author: w-5118db8e0c76
scope:
  - clipper/moments.py
  - tests/test_moments.py
about: TASK-5118db8e0c76
seq: 2
schema: 4
version: 1
---

 donne 3 Sentence words=0 -> _bonus(gaming-v2) renvoie speech_density -6.0 total -6.0, sans note. Hypothese : _speech_density compte 0 mot sur phrases sans words et traite 0 mot comme parole creuse. Refutation : un transcript avec words doit garder le malus existant (tests 2403-2431). Choix : transcript entier sans words + grille speech_density -> MomentsError ; moment dont une phrase recouvrante n'a pas de words -> signal non applique, note bonus speech_density_note.
