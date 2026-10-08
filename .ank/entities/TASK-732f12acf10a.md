---
id: TASK-732f12acf10a
type: task
slug: vision-un-lot-sauv-vision-partial-json-n-est-rep
title: "Vision : un lot sauvé (vision_partial.json) n'est repris que s'il porte les mêmes images ; review.json périmé écarté quand moments est refait"
created: 2026-10-07T23:47:32Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/vision.py
  - clipper/pipeline.py
  - tests/test_vision.py
  - tests/test_pipeline.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Revue r-pipeline 08/10 (research/reviews/pipeline.md, Important 3 et 4, preuves research/reviews/scratch-pipeline/repro_vision_partial.py et repro_review_stale.py). (1) vision : chaque lot sauvé dans vision_partial.json enregistre les chemins d'images (paths) qu'il couvre, comme action.py ; un lot sauvé n'est repris que si ses paths sont identiques à ceux du lot recalculé, sinon il est recalculé ; avec --force (étape vision forcée) vision_partial.json est ignoré et supprimé. (2) pipeline : quand l'étape moments est refaite (forcée ou rejeu), un review.json existant (décisions de la revue en mode review, indexées par moment) est mis de côté (renommé avec horodatage, journal INFO) au lieu d'être appliqué aux nouveaux moments renumérotés ; mode auto inchangé. (3) Tests : lot sauvé avec d'autres images -> recalculé ; lot identique -> repris ; --force -> partial ignoré ; review.json mis de côté après moments forcé, jamais appliqué aux nouveaux moments. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/7a0ee0e9f895@f1f3e31
    tree: scope/acc8962970e9
    criteria: 9f89c618f75f
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
