---
id: TASK-2cbb09ebef58
type: task
slug: jury-le-cache-de-prompt-ne-sert-toujours-pas-ent
title: "jury : le cache de prompt ne sert toujours pas entre les rôles (diagnostic + correctif)"
created: 2026-09-29T22:39:08Z
author: nicoc@zedk_ordi
status: in_progress
scope:
  - clipper/jury.py
  - clipper/llm
  - tests/test_jury.py
  - tests/test_llm_claude_cli.py
blocked_by: []
done_criteria: |
  Test unitaire : pour deux rôles d'un même modèle, la commande claude et le message ne diffèrent qu'après un préfixe commun (flags compris) ; contrôle réel noté dans ank log avec cache_read du 2e appel ; toute la suite pytest verte.
criteria_by: creator
verify: [tests]
schema: 4
version: 2
---

Mesure réelle WVjOSRFWm4c (137 min, 2026-09-29, workspace/WVjOSRFWm4c/llm_usage.jsonl) : jury_monteur/avocat/retention (opus) relisent ≤ 2,4k tokens de cache ; TASK-2852 puis TASK-b0fa (schéma remonté dans le prompt) n'ont pas suffi. Diagnostiquer ce qui diffère réellement entre 2 appels claude -p de rôles différents (system prompt, --json-schema qui devient un outil de sortie structurée, ordre, modèle) et corriger : ex. même --json-schema pour tous les rôles d'un modèle (schéma union ou enveloppe commune), consigne du rôle en fin de message, appels séquentiels d'un rôle puis les autres dans la fenêtre du cache. Ne pas changer le jugement. Preuves par TESTS UNITAIRES (commande claude construite, contenu envoyé, nb de tours...) ; au plus 1 appel réel de contrôle (skipif par défaut, CLIPPER_CLAUDE_INTEGRATION=1), résultat dans ank log. Le contrôle réel : 2 rôles successifs, le 2e doit montrer cache_read_tokens >> 2k.
