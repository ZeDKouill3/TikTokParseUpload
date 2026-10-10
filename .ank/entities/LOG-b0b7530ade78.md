---
id: LOG-b0b7530ade78
type: log
title: "Rouge constaté : exploration jamais placée (2 tests R6 rouges avant code). Cause : explorations"
created: 2026-10-10T01:20:04Z
author: w-96a89bb3e429
scope:
  - clipper/repartition.py
  - tests/test_repartition.py
  - CHANGELOG.md
about: TASK-96a89bb3e429
seq: 2
schema: 4
version: 1
---

 traitées dans la boucle par score, donc battues. Fix : réservation avant remplissage (_reserve_exploration), explorations exclues de la boucle principale. Clause 'aucun hors soir' : note ajoutée. Test 'deux par jour' durci (30 clips) pour être rouge avant code. Golden 'sans explo' capturé sur code d'origine : plan identique. Ciblé : 84 verts. Constat source research/reviews/plan-jury-retention.md absent du worktree (local, ignoré) : non vérifié ici.
