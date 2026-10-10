---
id: TASK-d40ed713c6e8
type: task
slug: r-partition-web-le-vivier-de-l-cran-et-le-put-ap
title: "Répartition web : le vivier de l'écran et le PUT appliquent aussi les exclusions R2 (sources exclues, vidéo en traitement)"
created: 2026-10-10T02:45:16Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/repartition.py
  - clipper/web/app.py
  - tests/test_repartition.py
  - tests/test_web.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Constat et preuve : E:\ClaudeRandom\TiktokParseUpload\research\reviews\revue-merges-nuit.md (local), I2 ; script research/reviews/scratch-revue-merges-nuit/c_pool_web_ignore_r2.py. account_pool et line_error (clipper/repartition.py) ne retirent que les séries ; SPEC-78dc R2 retire aussi les clips d'une source de excluded_sources et ceux dont la vidéo est dans la file de traitement (waiting/running), ce que _pool fait pour compute_plan. Correctif : extraire une fonction partagée (raison d'exclusion d'un clip : multi_part_series, excluded_source, in_processing_queue) utilisée par _pool, account_pool et line_error ; le PUT refuse en 422 avec la raison, le fichier du jour inchangé. Critères (tests CPU) : avec excluded_sources = ['banni'] et une vidéo en file, account_pool ne rend ni le clip banni ni celui de la vidéo en file ; PUT de chacun -> 422 avec excluded_source / in_processing_queue, fichier inchangé ; compute_plan inchangé (tests R2 existants verts). CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
