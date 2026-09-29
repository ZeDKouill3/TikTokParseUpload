---
id: LOG-75ee075ee77b
type: log
title: "llm.usage_log(path) implemente : global de module (pas contextvar) pour propager aux threads ;"
created: 2026-09-29T13:29:24Z
author: w-15129acecf26
scope:
  - clipper/llm/__init__.py
  - clipper/pipeline.py
  - tests/test_llm.py
  - tests/test_pipeline.py
about: TASK-15129acecf26
seq: 2
schema: 4
version: 1
---

 ask() prend usage_log_path explicite en priorite sinon le defaut du contexte. tests/test_llm.py verts (68 passed).
