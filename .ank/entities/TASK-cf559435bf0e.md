---
id: TASK-cf559435bf0e
type: task
slug: captions-titre-d-cran-court-avec-un-emoji-screen
title: "captions : titre d'écran court avec un emoji (screen_title)"
created: 2026-09-28T17:26:08Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/captions.py
  - tests/test_captions.py
blocked_by: []
done_criteria: |
  SPEC-6127 (format letterbox) : chaque clip de captions.json gagne screen_title, le titre affiché en haut de l'écran pendant tout le clip : produit par le même appel clipper.llm que title/caption/hook_text (schéma JSON étendu, champ obligatoire), en français, accrocheur, au plus screen_title_words_max mots (CONFIG_DEFAULTS, 8 par défaut, même règle de comptage que hook_text) et contenant exactement un emoji (vérification locale après le schéma : zéro ou plusieurs emojis, ou trop de mots = réponse invalide renvoyée au LLM pour correction comme hook_text, puis échec explicite, jamais d'emoji ajouté ni de titre tronqué en silence, ADR-ad2e) ; le prompt explique l'usage (titre sur la bande floue au-dessus de la vidéo) ; tests avec FakeBackend : réponse valide conservée, sans emoji -> correction demandée puis échec, deux emojis -> échec, trop long -> échec, emoji composé (drapeau, emoji avec variation) compté comme un seul ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
