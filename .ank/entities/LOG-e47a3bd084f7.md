---
id: LOG-e47a3bd084f7
type: log
title: "released: critere inatteignable dans le scope : repair_attempts=1 par defaut fait re-appeler le"
created: 2026-09-25T18:42:46Z
author: w-cf1c
scope:
  - clipper/llm/__init__.py
  - tests/test_llm.py
  - clipper/captions.py
  - tests/test_captions.py
about: TASK-cf1c258aced8
seq: 3
schema: 4
version: 1
---

 modele apres une SchemaError, et 9 tests hors scope ne scriptent qu'UNE reponse invalide au FakeBackend (epuise -> AssertionError au lieu de SchemaError) : test_moments (test_invalid_llm_answer_fails_and_writes_nothing, fichier claime par TASK-e493), test_parts x2, test_qa, test_reframe, test_subtitles, test_transcribe x2, test_vision. Fix : ajouter ces 7 fichiers de test au scope (scripter 2 reponses invalides ou repair_attempts=0) ou clipper/llm/fake.py. Travail du scope fait et vert (llm.ask check=/repair_attempts, captions branche, tests) : commit WIP sur task/TASK-cf1c-llm-repair.
