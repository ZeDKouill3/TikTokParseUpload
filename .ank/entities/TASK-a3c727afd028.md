---
id: TASK-a3c727afd028
type: task
slug: apprentissage-un-clip-publi-sans-statistique-ne
title: "Apprentissage : un clip publié sans statistique ne compte plus comme « résultat parfait » dans la calibration du jury"
created: 2026-10-09T22:52:42Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/learning.py
  - clipper/jury_calibration.py
  - tests/test_learning.py
  - tests/test_jury_calibration.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Constat et preuve : research/reviews/perf-0910.md (local ; scripts de preuve sous research/reviews/scratch-perf-0910/). (Important 2) learning.sync ajoute à linked tous les clips reliés à un post AVANT le test de maturité et _calibrate les passe tous à jury_calibration.calibrate ; _outcomes moyenne les signaux par moment et un clip publié a toujours qa passed = 1.0 : un clip immature (aucune stat) vaut 1.0, au-dessus d'un clip scoré au rang 0.99 ((1+0.99)/2) ; le signal qa, constant sur les clips publiés, écrase le rang de moitié (ADR-1cf0 : vérité terrain = signaux réels ; ADR-ad2e). Correctif : linked ne contient que les clips qui ont (ou reçoivent à ce passage) une entrée stats ; dans jury_calibration._outcomes, quand la métrique est une statistique de plateforme (views_percentile ou pct_watched), le résultat d'un moment est la statistique seule (qa ignoré), et un moment sans statistique est exclu. Critère : fixtures A (rang 0.99), B (0.01), C (relié, immature) -> C absent du calcul, A > B ; aucun clip sans stats ne compte dans 'clips' de jury_weights.json ; tests existants de calibration verts (adapter seulement ceux qui encodaient le défaut, en le disant dans le log). Tests CPU sans réseau. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/4ba84e121d43@0224aba
    tree: scope/482f526337fe
    criteria: 78438c027a82
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 5
---
