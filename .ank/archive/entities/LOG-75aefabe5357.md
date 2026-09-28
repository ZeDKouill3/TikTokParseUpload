---
id: LOG-75aefabe5357
type: log
title: "Fix v2 : simple exclusion de 'failed' du baseline suffisait pas -- une lecture du watcher juste"
created: 2026-09-25T17:57:21Z
author: w-8c47
scope:
  - clipper/__main__.py
  - tests/test_cli_progress.py
about: TASK-8c47eddb7830
seq: 3
schema: 4
version: 1
---

 avant que la relance ecrive 'running' choppe le vieux statut failed et l'annonce prematurement (echec fige, jamais de 'terminee'). Repro test rouge confirme ce mecanisme exact. Fix final : stale_snapshot (etat complet par etape non-done au moment du claim) compare a chaque poll ; tant qu'identique, l'etape est ignoree (pas encore repartie) ; des qu'elle differe, traitement normal. tests/test_cli_progress.py : 6 passed.
