---
id: LOG-8feb6d50202e
type: log
title: "RED confirmé : test_a_postpone_error_on_one_due_entry... échoue : PublishError de postpone remonte"
created: 2026-10-09T07:09:10Z
author: w-748696ea666f
scope:
  - clipper/worker.py
  - tests/test_worker.py
  - CHANGELOG.md
about: TASK-748696ea666f
seq: 3
schema: 4
version: 1
---

 à _publish_due, 2e entrée due (ef34ab) jamais tentée, log 'publication TikTok impossible'. Correction : try/except PublishError autour de postpone dans _publish_one -> warning + _wait(raison) -> return False (passe à l'entrée suivante).
