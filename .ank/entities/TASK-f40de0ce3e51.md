---
id: TASK-f40de0ce3e51
type: task
slug: comptes-pr-t-publier-automatique-selon-la-connex
title: "Comptes : « prêt à publier » automatique selon la connexion vérifiée (SPEC-e500 R3)"
created: 2026-10-01T21:43:02Z
author: nicoc@zedk_ordi
status: in_progress
scope:
  - clipper/accounts.py
  - clipper/browser.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_accounts.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  R3 de SPEC-e500759ebe68 tenue, tests sans navigateur ni réseau : (1) ready_to_publish est calculé : vrai si et seulement si la connexion TikTok du profil est vérifiée (lecture locale des cookies, R2) et qu'aucun arrêt R4 de SPEC-9225 n'est en attente ; recalculé à l'ouverture de l'écran, après Se connecter et avant chaque publication ; chaque changement est journalisé avec sa raison ; (2) plus aucune coche manuelle : PUT /api/accounts/{id}/ready supprimé (ou refusé 405 avec message) ; dans l'écran Comptes, la case est en lecture seule (état + raison) ; cliquer dessus quand le compte n'est pas prêt lance « Se connecter » (Chrome normal), puis revérifie à la fermeture et met l'état à jour ; (3) après un arrêt R4, bouton « J'ai réglé le problème » qui efface l'arrêt en attente et revérifie la connexion ; (4) un compte déjà connecté (cas réel : profil connecté avant l'existence de la case) apparaît prêt sans action ; (5) tests existants verts. python -m pytest -q tests/test_accounts.py tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

Implémente la nouvelle R3 de SPEC-e500759ebe68 (ratifiée 2026-10-01, successeur de SPEC-00d1) : aujourd'hui la case est cochée à la main (PUT /api/accounts/{id}/ready).
