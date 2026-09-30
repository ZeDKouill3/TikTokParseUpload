---
id: LOG-beafd46f3356
type: log
title: "Controle reel : 4 .ass de la demo (v2887271276, clips 00/01/02/05, style split) regeneres avec le"
created: 2026-09-30T17:28:02Z
author: w-9ee7a0c3cb62
scope:
  - clipper/subtitles.py
  - tests/test_subtitles.py
  - docs/GUIDE.md
about: TASK-9ee7a0c3cb62
seq: 4
schema: 4
version: 1
---

 fix dans une copie de travail isolee (research/madajel/silences/_regen, jamais workspace/ ni output/). Mesure sur les 40 vrais silences (>gap_s=0.6s entre deux mots consecutifs de transcript.json, tous clips confondus, duree cumulee 152.2s) : duree totale desormais affichee pendant ces silences 55.0s -> 14.5s (ecoulement du hold_s=0.3s en debut de chaque silence, comportement voulu par le critere) ; pire cas individuel 16.76s -> 2.78s (l'evenement 'L'ECHAPPE. AH,' de 00.ass, avant 17.34s de Dialogue pour 16.76s de vrai silence, est desormais deux evenements distincts qui se terminent au plus 0.3s apres leur dernier mot). Detail par clip (evenements base >1.5s, indicateur grossier) : 00 4->3 (24.8s->6.6s), 01 5->4 (15.4s->9.4s), 02 12->9 (31.6s->16.7s), 05 8->8 (20.4s->17.3s). Tests unitaires : 81 passed, 1 skipped (tests/test_subtitles.py), 10 passed (tests/test_pipeline.py -k subtitle).
