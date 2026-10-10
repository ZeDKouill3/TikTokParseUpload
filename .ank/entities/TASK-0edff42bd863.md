---
id: TASK-0edff42bd863
type: task
slug: audit-lot-i-scenes-criture-v-rifi-e-force-propre
title: "Audit lot I : scenes : écriture vérifiée, `--force` propre"
created: 2026-10-10T18:25:23Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
blocked_by: []
done_criteria: |
  Lot I de l'audit complet du 10/10 (contre-vérifié par Fable). Défauts couverts : media-I3, media-M1. Détails, scénarios, preuves rejouables (scripts dans scratch-<domaine>/) : rapports E:\ClaudeRandom\TiktokParseUpload\research\reviews\audit-1010\<domaine>.md (coeur, publication, web, jury, image, stats, media, veille, installeur ; id = <domaine>-I<n>/M<n>) et E:\ClaudeRandom\TiktokParseUpload\research\reviews\audit-1010\contre-verif.md (verdicts, lot I) ; LECTURE SEULE, ne rien écrire dans research/. Correctif attendu : `clipper/scenes.py`, `tests/test_scenes.py`. Critère CPU : `imwrite` monkeypatché à `False` → `ScenesError`, pas de `scenes.json` ; `--force` vide `frames/` avant d'écrire. Pour chaque défaut : test de régression ROUGE avant le correctif, vert après ; tests existants des modules touchés verts ; aucune valeur de secours silencieuse (ADR-ad2e) ; si un défaut s'avère faux ou exige une décision humaine (amendement de spec/ADR), le dire dans ank log et ne pas le corriger.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---
