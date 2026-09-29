---
id: TASK-d5e32c9d1ab8
type: task
slug: transcribe-la-correction-llm-renvoie-seulement-l
title: "transcribe : la correction LLM renvoie seulement les mots corrigés, pas tout le texte"
created: 2026-09-29T19:11:31Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
blocked_by: []
done_criteria: |
  La sortie attendue du LLM (schéma) est une liste de corrections ; le code les applique sur transcript_raw ; correction incohérente refusée + journalisée ; tests FakeBackend verts ; toute la suite pytest verte.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Mesure llm_usage.jsonl sur oBfOhJKT8lk : transcript_fix = 6 appels sonnet, 68 605 tokens de sortie, 4,42 USD équivalent API, 669 s : le modèle réécrit toute la transcription. Lui faire renvoyer uniquement la liste des corrections (index de segment ou de mot, ancien, nouveau), appliquées ensuite par le code ; une correction qui ne correspond pas au texte est refusée et journalisée (ADR-ad2e), pas appliquée en silence.
