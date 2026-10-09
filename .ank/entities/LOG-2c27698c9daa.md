---
id: LOG-2c27698c9daa
type: log
title: "Début TDD (méthode tdd). Clauses: (1) Worker.tick appelle repartition.run_if_due(now, config=) à"
created: 2026-10-09T14:13:53Z
author: w-0350d226d693
scope:
  - clipper/worker.py
  - tests/test_worker.py
  - CHANGELOG.md
about: TASK-0350d226d693
seq: 1
schema: 4
version: 1
---

 chaque tour après _learning_due, coureur injectable repartition_runner au constructeur; (2) RepartitionError/PublishError/AccountsError/TikTokError/ConfigError/OSError/ValueError ne sortent jamais de tick, journalisées une fois; (3) [repartition] enabled=false -> aucun appel; (4) CHANGELOG [Non publié] Ajouté une ligne.
