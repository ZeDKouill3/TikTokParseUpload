---
id: TASK-6e434ac2f22c
type: task
slug: clip-gard-sous-min-score-apr-s-le-recalcul-post
title: "Clip gardé sous min_score après le recalcul post-vision (7VaA clip 07 : 48,7 < 60)"
created: 2026-09-30T09:46:57Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/moments.py
  - clipper/pipeline.py
  - tests/test_moments.py
  - tests/test_pipeline.py
blocked_by: []
done_criteria: |
  Cause identifiée et consignée (ank log) : pourquoi workspace/7VaA8XUKrAY/moments.json garde un moment final_score 48,7 alors que rubric.toml min_score = 60 ; comportement corrigé selon SPEC-0eec (lire la règle : le score final après vision doit-il repasser min_score et le non-chevauchement ?) : si oui, le moment passé sous le seuil après vision n'est pas rendu, et c'est journalisé (raison explicite, ADR-ad2e) ; test unitaire FakeBackend qui reproduit le cas (score >= seuil avant vision, < seuil après) ; si la spec dit l'inverse, ank release avec la citation exacte.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 3
---

Passage réel 7VaA8XUKrAY 2026-09-30 10:11-10:25 : 8 clips, le 07 (15,29-95,55 s, « L'affaire Bruel explose ») a final_score 48,7, sous min_score 60 (rubric.toml). Hypothèse : sélection faite sur le score avant vision, puis recalcul après vision (test_moments_gets_feedback_examples_and_is_rescored_after_vision_without_llm) sans réappliquer min_score. Ne relancer aucune vidéo ; rejouer seulement le code sur les JSON existants (copie) ou via tests.
