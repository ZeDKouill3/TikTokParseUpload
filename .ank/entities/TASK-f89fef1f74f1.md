---
id: TASK-f89fef1f74f1
type: task
slug: jury-spectateur-erreur-400-max-4-cache-control-f
title: "jury_spectateur : erreur 400 'max 4 cache_control, found 5' ; et ce 400 doit être un échec explicite, pas transitoire"
created: 2026-09-30T07:23:03Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/jury.py
  - clipper/llm
  - tests/test_jury.py
  - tests/test_llm_claude_cli.py
  - tests/test_llm.py
blocked_by: []
done_criteria: |
  Test unitaire reproduisant le message du rôle spectateur (avec ses images/blocs) : nombre total de blocs cache_control <= 1 ; test : un 400 cache_control donne LLMError (pas Transient) ; appel réel de contrôle du rôle jury_spectateur sur un vrai candidat (skipif, CLIPPER_CLAUDE_INTEGRATION=1) sans 400, noté dans ank log ; toute la suite pytest verte.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/dd26c41e7eaa@debe915
    tree: scope/166f9f6a0d60
    criteria: 8c6dad6cd8f0
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Passage réel 7VaA8XUKrAY (2026-09-30 01:48, research/retranscribe/reserve-test.log + workspace/7VaA8XUKrAY/llm_usage.jsonl) : le cache marche pour jury_avocat/monteur/conformite (~42k relus), mais jury_spectateur (sonnet) échoue : 'API Error: 400 A maximum of 4 blocks with cache_control may be provided. Found 5.' malgré TASK-746c (1 marqueur). Diagnostiquer le message réellement envoyé pour ce rôle (images ? plusieurs blocs ? marqueurs ajoutés par claude -p lui-même) et corriger pour rester sous la limite (si besoin : aucun cache_control de notre part sur ce chemin). Aussi : TASK-746c a classé ce 400 comme TransientLLMError (vidéo mise en attente) ; c'est déterministe -> échec explicite (LLMError) avec message clair (ADR-ad2e).
