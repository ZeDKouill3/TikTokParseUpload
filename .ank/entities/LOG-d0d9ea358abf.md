---
id: LOG-d0d9ea358abf
type: log
title: "Matrice complete 7VaA8XUKrAY (margin 1/2/5s x width 256/480, stride n/a car source 25i/s<=30) :"
created: 2026-10-01T12:15:15Z
author: w-908e2a684d7e
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
about: TASK-908e2a684d7e
seq: 5
schema: 4
version: 1
---

 width=480 n'apporte AUCUN gain de taux (99.7-100% identique a 256 a chaque marge) et coute 30-50% de temps en plus (441s vs 295s @margin5, 397s vs 303s @margin2, 455s vs 317s @margin1) -- ecarte. Marge 1/2/5s : taux quasi identique (99.7-100%) car cette video est presque entierement parlee (97.9-98.9% decode dans tous les cas), marge peu discriminante ici. Width=480 ecarte, passage aux mesures utiles sur v2887271276 (3h, 60i/s, ou stride compte) : margin x {1,2,5} x stride x {1,2} a width=256 fixe (5 combos, budget restant ~2h20).
