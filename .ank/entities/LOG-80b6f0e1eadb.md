---
id: LOG-80b6f0e1eadb
type: log
title: Residu distinct trouve en verifiant le controle reel, hors scope de ce critere (nouveau mecanisme,
created: 2026-09-30T17:28:12Z
author: w-9ee7a0c3cb62
scope:
  - clipper/subtitles.py
  - tests/test_subtitles.py
  - docs/GUIDE.md
about: TASK-9ee7a0c3cb62
seq: 5
schema: 4
version: 1
---

 pas les 3 du critere) : le cas 05 (gap 2.78s couvert apres fix, le pire restant) vient d'un jeton colle par apostrophe (_GLUED_PREFIXES) -- _units() fusionne "'accord" (84.52-85.04s) dans la meme unite que " d" (80.80-81.74s) avant meme que _group_words() ne regarde les ecarts, alors qu'un vrai silence de 2.78s les separe (transcript.json v2887271276, clip 05 relatif ~81.74-84.52s : "... dehors d' [pause 2.78s] accord mais..."). Le decoupage par gap_s de ce critere opere entre unites, jamais a l'interieur d'une unite deja fusionnee par elision. Cree une tache separee (ne widen pas ce diff, ank-diagnose) : verifier le gap a l'interieur de _units() avant de coller un jeton d'elision/ponctuation, pas seulement entre unites.
