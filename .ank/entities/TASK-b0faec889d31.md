---
id: TASK-b0faec889d31
type: task
slug: llm-claude-cli-images-pass-es-dans-le-message-st
title: "llm claude-cli : images passées dans le message (stream-json), 1 tour sans outil Read ; + cache jury réel"
created: 2026-09-29T20:59:24Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/llm
  - clipper/jury.py
  - clipper/transcribe.py
  - tests/test_llm.py
  - tests/test_llm_claude_cli.py
  - tests/test_jury.py
  - tests/test_transcribe.py
blocked_by: []
done_criteria: |
  Tests unitaires : (1) un appel avec images construit une commande claude -p sans outil Read ni --add-dir, avec --input-format stream-json et les images en blocs base64 dans le message ; (2) les prompts des rôles du jury d'un même modèle ont un préfixe identique incluant tout ce qui précède la consigne du rôle (schéma compris) ; (3) les appels LLM faits depuis des threads pendant transcribe sont journalisés dans llm_usage.jsonl ; toute la suite pytest verte ; mesure réelle avant/après notée dans ank log.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Mesure réelle ivl0nxa3C7o (llm_usage.jsonl) : vision 108 appels, ~90k tokens relus en cache par appel (8,21 USD) ; qa ~235k par appel (4,70 USD) ; la planche unique (TASK-c84e) n'a rien réduit. Hypothèse : claude_cli.py passe les images via l'outil Read (--tools Read, --add-dir), donc plusieurs tours agentiques qui relisent tout le contexte. Correctif : envoyer les images comme blocs image dans le message utilisateur via --input-format stream-json (sur stdin), sans aucun outil (--tools ''), réponse en 1 tour. Jury (TASK-2852) : le cache relu reste ~1,2k, le préfixe commun ne sert pas ; vérifier si --json-schema (différent par rôle) ou le system prompt casse le préfixe, et corriger (ex. schéma commun + consigne de rôle en fin, ou schéma identique). Aussi : transcript_fix n'apparaît pas dans llm_usage.jsonl lors d'un passage transcribe (appels en threads ?) : corriger la propagation du journal. Preuves par TESTS UNITAIRES (demande utilisateur) : commande claude construite, contenu stdin stream-json, nombre de tours, préfixes identiques, journalisation depuis threads. Un seul appel réel de contrôle autorisé (skipif par défaut, CLIPPER_CLAUDE_INTEGRATION=1) pour mesurer tokens avant/après sur 1 image ; résultat dans ank log.
