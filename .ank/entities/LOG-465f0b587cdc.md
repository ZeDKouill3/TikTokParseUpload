---
id: LOG-465f0b587cdc
type: log
title: llm.ask(check=, repair_attempts defaut 1) implemente, tests repair verts. Mais repair_attempts=1
created: 2026-09-25T18:39:58Z
author: w-cf1c
scope:
  - clipper/llm/__init__.py
  - tests/test_llm.py
  - clipper/captions.py
  - tests/test_captions.py
about: TASK-cf1c258aced8
seq: 2
schema: 4
version: 1
---

 par defaut casse 9 tests hors scope qui scriptent UNE seule reponse invalide au FakeBackend (epuise a la reparation -> AssertionError) : test_moments::test_invalid_llm_answer_fails_and_writes_nothing, test_parts (2), test_qa, test_reframe, test_subtitles, test_transcribe (2), test_vision. Scope n'inclut ni ces tests ni clipper/llm/fake.py.
