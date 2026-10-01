---
id: TASK-02dbe6c8bb59
type: task
slug: jury-confiance-par-juge-et-par-moment-d-bat-sur
title: "Jury : confiance par juge et par moment, débat sur confiance basse, médiane pondérée (SPEC-73d0)"
created: 2026-10-01T13:23:00Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/jury.py
  - clipper/moments.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_jury.py
  - tests/test_moments.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Règles R1 à R6 de SPEC-73d05edb4a74 tenues à la lettre, prouvées par tests ciblés avec FakeBackend (jamais le vrai Claude) : (1) le schéma JSON des juges exige confidence entier 0-100 aux tours 1 et 2 ; réponse sans confidence ou hors bornes = réponse invalide (même traitement que les autres champs) ; (2) un candidat passe au débat si un juge a une confiance < [jury] debate_confidence_below (défaut 40, CONFIG_DEFAULTS), en plus de l'écart de scores ; (3) médiane par critère pondérée par poids de calibration × max(confidence/100, [jury] min_confidence_weight défaut 0,2), déterministe, cas chiffrés testés ; non-régression : confiances toutes égales -> scores identiques à l'agrégation actuelle ; (4) moments.json et le JSON du jury gardent la confiance de chaque juge par tour et la confiance agrégée (médiane des confiances finales) ; la console l'affiche dans l'écran Revue et sur la fiche d'un clip (tests API + statique) ; (5) aucun changement de mode auto/review ; (6) tests existants verts. python -m pytest -q tests/test_jury.py tests/test_moments.py tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Implémente SPEC-73d05edb4a74 (ratifiée 2026-10-01).
