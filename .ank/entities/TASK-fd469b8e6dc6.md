---
id: TASK-fd469b8e6dc6
type: task
slug: coach-des-prompts-du-jury-les-r-sultats-r-els-de
title: "Coach des prompts du jury : les résultats réels des clips publiés viennent des vues (stats), plus d'un 1,0 constant"
created: 2026-10-08T00:03:52Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/jury_coach.py
  - tests/test_jury_coach.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Revue r-veille-stats 08/10 (research/reviews/veille-stats.md I4 et M1). (1) jury_coach._real_outcomes : pour un clip publié, le résultat réel vient des entrées stats qui portent video_id/moment_id (views_percentile à 3 jours, comme la boucle d'apprentissage TASK-7136/c108/9dac) et non plus seulement de qa + décision (qui vaut 1,0 pour tout clip publié) ; un clip publié sans stats mûres est exclu des cas (jamais 1,0 par défaut, ADR-ad2e). (2) M1 si dans le même fichier ou trivialement voisin : sinon le noter dans le rapport du worker sans le corriger. (3) Tests : deux clips publiés de percentiles différents -> résultats réels différents ; clip publié sans stats -> exclu. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/fd02fa05e0a4@33370a4
    tree: scope/1d1cad2e47cf
    criteria: 21c9afba45bc
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 5
---
