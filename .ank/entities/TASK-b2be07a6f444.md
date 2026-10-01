---
id: TASK-b2be07a6f444
type: task
slug: acc-s-distant-de-bout-en-bout-serve-host-page-je
title: accès distant de bout en bout (serve --host, page jeton, notifications navigateur) et documentation de la console v2 (GUIDE.md, README, CHANGELOG)
created: 2026-09-30T20:44:58Z
author: w-plan-web
status: in_progress
scope:
  - clipper/__main__.py
  - clipper/web/app.py
  - clipper/web/static/**
  - docs/GUIDE.md
  - README.md
  - CHANGELOG.md
  - tests/test_web.py
blocked_by: [TASK-503d3672d389, TASK-750899529c83, TASK-7d86af5f2d23, TASK-ee5dbed502d7]
done_criteria: |
  tests/test_web.py prouve : python -m clipper serve --host 0.0.0.0 sans [web] token refuse de démarrer avec un message en français qui nomme la clé ; avec token, uvicorn est lancé sur l'hôte demandé (injecté) et la page servie sans cookie affiche la saisie du jeton ; le JS demande la permission de notification navigateur depuis un réglage local (jamais au chargement) et notifie sur les événements done/failed/awaiting_review/queued ; docs/GUIDE.md a une section 'Console de gestion' qui décrit les 8 écrans, la file, les presets en surcouche (avec un exemple ma_chaine), state/, la surveillance, l'accès distant par jeton et ses limites (réseau local seulement, pas de TLS) ; README et CHANGELOG mentionnent la console v2 ; aucun nom réel (grep). python -m pytest -q tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 3
---

SPEC-c100 T5, T7 ; ADR-4f6e §5. Le jeton protège un accès sur le réseau local depuis le téléphone ; la documentation dit explicitement de ne pas exposer le port sur Internet sans reverse proxy TLS.
