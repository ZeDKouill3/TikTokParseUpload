---
id: LOG-deab0e1542ee
type: log
title: "TDD termine : bloc commun devant les prompts de juges, role a la fin ; shuffle des candidats"
created: 2026-09-29T19:25:28Z
author: w-2852b3fd7518
scope:
  - clipper/jury.py
  - tests/test_jury.py
about: TASK-2852b3fd7518
seq: 2
schema: 4
version: 1
---

 partage par modele (memes refs/ordre) ; _run_round en 2 vagues (leader par modele puis le reste) ; test_judges_run_in_parallel remplace par test des 2 vagues (horodatage, plus fiable qu'une barriere partagee) ; test_shuffle_is_deterministic_and_specific_to_each_judge adapte au regroupement par modele. Suite tests/test_jury.py verte (35 passed, 1 skipped). Suite pytest complete en cours (longue, >2min).
