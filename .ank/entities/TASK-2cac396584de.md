---
id: TASK-2cac396584de
type: task
slug: transcribe-r-duire-le-co-t-de-transcript-fix-5-8
title: "transcribe : réduire le coût de transcript_fix (5,82 USD sur 137 min)"
created: 2026-09-29T22:39:08Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
blocked_by: []
done_criteria: |
  Test unitaire : le prompt d'un morceau est au format compact (pas de JSON de segments complet), le préfixe consignes+vocabulaire est identique entre morceaux ; taille par appel avant/après notée dans ank log ; toute la suite pytest verte.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/e06b3538a235@00aeca0
    tree: scope/e7b5bb5b37fc
    criteria: 0d4fb12fbefc
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Mesure réelle WVjOSRFWm4c (137 min, 2026-09-29, workspace/WVjOSRFWm4c/llm_usage.jsonl) : transcript_fix = 8 appels sonnet, 37k tokens de sortie (déjà réduit par TASK-d5e3) mais 5,82 USD : le coût vient surtout de l'entrée (texte envoyé par morceau, réécrit en cache à chaque appel). Mesurer la taille envoyée par appel, puis réduire : n'envoyer que le texte nécessaire (sans horodatages ni métadonnées JSON verbeuses, format compact ligne par segment), vocabulaire une fois, morceaux dimensionnés pour que le préfixe commun (consignes + vocabulaire) soit en cache. Ne pas dégrader la correction. Preuves par TESTS UNITAIRES (commande claude construite, contenu envoyé, nb de tours...) ; au plus 1 appel réel de contrôle (skipif par défaut, CLIPPER_CLAUDE_INTEGRATION=1), résultat dans ank log.
