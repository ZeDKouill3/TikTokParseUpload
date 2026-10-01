---
id: TASK-7d86af5f2d23
type: task
slug: web-cran-statistiques-r-sultats-par-clip-via-out
title: "web : écran Statistiques (résultats par clip via outcomes, décisions et QA, coûts LLM par vidéo/usage/période, durée par étape, import CSV)"
created: 2026-09-30T20:44:58Z
author: w-plan-web
status: in_progress
scope:
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_web.py
blocked_by: [TASK-aad32da87c1e]
done_criteria: |
  tests/test_web.py prouve avec des fixtures state/outcomes.jsonl, state/feedback.jsonl, workspace/*/llm_usage.jsonl et pipeline.json : GET /api/stats?since=&until= renvoie clips (résultats outcomes joints au sidecar et à la décision humaine), llm_cost par vidéo, par usage et par jour, steps (durée moyenne et dernière par étape sur les vidéos done), counts (vidéos par statut) ; POST /api/stats/import (CSV multipart) appelle outcomes.import_stats et renvoie le nombre de lignes ou 422 avec detail ; l'écran stats de la page montre ces quatre blocs avec une période sélectionnable et un bouton d'import. python -m pytest -q tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 3
---

SPEC-c100 E7. Les graphiques restent en SVG/canvas maison ou CSS (aucune bibliothèque externe, ADR-09ad sans build). Les vues/rétention n'existent que via le CSV importé (clipper.outcomes) tant que l'autopost n'existe pas.
