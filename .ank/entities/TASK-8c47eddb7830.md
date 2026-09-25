---
id: TASK-8c47eddb7830
type: task
slug: cli-progression-annoncer-aussi-une-tape-relanc-e
title: "CLI progression : annoncer aussi une étape relancée après un échec"
created: 2026-09-25T17:53:09Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/__main__.py
  - tests/test_cli_progress.py
blocked_by: []
done_criteria: |
  Constat essai réel 2026-09-25 : en relançant run après un échec de vision, rien ne s'affiche car _baseline_progress range les étapes failed avec les étapes déjà faites. Une étape en échec avant l'appel est annoncée quand elle repart ('[etape] démarrée' puis 'terminée en N s' ou l'échec) ; les étapes done avant l'appel restent silencieuses ; test de régression dans tests/test_cli_progress.py ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---
