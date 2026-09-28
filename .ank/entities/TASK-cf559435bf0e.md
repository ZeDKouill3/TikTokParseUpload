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
  SPEC-6127 (format letterbox) : chaque clip de captions.json gagne screen_title, titre affiché en haut de l'écran sur un encadré blanc pendant tout le clip : produit par le même appel clipper.llm que title/caption/hook_text (schéma JSON étendu, champ obligatoire), dans la langue du clip, court et accrocheur : au plus screen_title_words_max mots (CONFIG_DEFAULTS, 6 par défaut ; l'emoji ne compte pas comme un mot ; même règle de comptage que hook_text) et exactement un emoji, défini comme un seul point de code Extended_Pictographic, éventuellement suivi de U+FE0F (VS16) et/ou d'un modificateur de teint ; séquences ZWJ et drapeaux (indicateurs régionaux) refusés car le rendu ne sait pas les composer. Vérification locale après le schéma : zéro ou plusieurs emojis, emoji composé, ou trop de mots = réponse renvoyée au LLM pour correction comme hook_text, puis échec explicite ; jamais d'emoji ajouté ni de titre tronqué en silence (ADR-ad2e) ; le prompt explique l'usage (titre de 5-6 mots dans un encadré au-dessus de la vidéo, un seul emoji simple). Tests avec FakeBackend : réponse valide conservée ; sans emoji -> correction demandée puis échec ; deux emojis -> échec ; 7 mots -> échec ; emoji + VS16 accepté ; emoji + teint accepté ; séquence ZWJ refusée ; drapeau refusé ; toute la suite pytest reste verte. Aucun worker ne touche tests/conftest.py.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 3
---
