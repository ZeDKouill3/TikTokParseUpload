---
id: TASK-15129acecf26
type: task
slug: pipeline-brancher-le-journal-de-consommation-llm
title: "pipeline : brancher le journal de consommation LLM par vidéo (workspace/<id>/llm_usage.jsonl)"
created: 2026-09-29T13:20:55Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/llm/__init__.py
  - clipper/pipeline.py
  - tests/test_llm.py
  - tests/test_pipeline.py
blocked_by: []
done_criteria: |
  Un passage clipper.pipeline sur une vidéo avec FakeBackend (qui rapporte un usage) écrit une ligne par appel LLM dans workspace/<id>/llm_usage.jsonl, y compris les appels faits depuis des threads ; ask() hors pipeline n'écrit rien ; toute la suite pytest verte.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/d9544f07a6a5@b33a22c
    tree: scope/b166ac4514e3
    criteria: 7be38e79ffb4
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

TASK-68eb a ajouté usage_log_path à clipper.llm.ask mais aucun appelant ne le passe : rien n'est journalisé. Solution la plus simple sans toucher chaque étape : un réglage de contexte dans clipper.llm (ex. contextvar ou fonction usage_log(path) en gestionnaire de contexte) que clipper.pipeline positionne pour la durée du passage sur une vidéo ; ask() l'utilise quand usage_log_path n'est pas donné. Les appels faits dans des threads (étapes parallélisées par clip) doivent aussi être journalisés. Plus un résumé par usage (tokens, coût) dans le journal de la vidéo à la fin du passage.
