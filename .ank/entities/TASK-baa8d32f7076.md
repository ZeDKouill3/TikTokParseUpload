---
id: TASK-baa8d32f7076
type: task
slug: reframe-la-webcam-visage-cadre-n-est-plus-vinc-e
title: "Reframe : la webcam (visage+cadre) n'est plus évincée des candidats, coupe journalisée, mémoire des images"
created: 2026-10-05T23:34:22Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
blocked_by: []
done_criteria: |
  Corriger I1, M1 et M2 de la revue Fable E:/ClaudeRandom/TiktokParseUpload/research/reviews/nuit.md (lire ces sections, preuves dans research/reviews/scratch-nuit/). I1 : à la fusion visage+cadre le candidat garde le support max (cadre) et n'est jamais évincé avant des cadres purs ; tout candidat coupé par facecam_candidate_max est écrit dans rejected avec raison explicite (ADR-ad2e, pas de perte silencieuse) ; le libellé envoyé à Claude ne ment plus sur le nombre d'images. M2 : deux cadres emboîtés sans visage ne sont plus étiquetés visage+cadre. M1 : _period_candidates ne garde plus 24 images pleines en float64 (crête mémoire réduite, ex. uint8 ou réduction d'échelle), même résultat sur les tests existants. Preuves par tests unitaires (détecteurs simulés, FakeBackend, aucun réseau, aucun vrai Claude) reproduisant chaque scénario du rapport, rouges avant le correctif.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---
