---
id: LOG-d942bef35c8c
type: log
title: Fix des tests de concurrence reelle (scope elargi tests/test_qa.py, tests/test_vision.py,
created: 2026-09-30T19:54:03Z
author: w-42a46cb23f78
scope:
  - pyproject.toml
  - tests/conftest.py
  - tests/test_qa.py
  - tests/test_vision.py
  - tests/test_transcribe.py
about: TASK-42a46cb23f78
seq: 9
schema: 4
version: 1
---

 tests/test_transcribe.py) : remplace le sleep fixe (time.sleep(0.05-0.15s) + comptage) par un chevauchement prouve par evenement (threading.Event) : chaque appel incremente un compteur sous verrou, signale l'evenement une fois 'expected' appels simultanement actifs, et attend cet evenement (timeout genereux 10s, jamais un sleep court) avant de se decrementer. Preuve deterministe du chevauchement au lieu d'une fenetre de temps qui peut etre ratee sous charge CPU (aucune valeur de secours : si le parallelisme reel n'atteint jamais 'expected', le test echoue proprement apres le timeout au lieu de rester bloque). 4 sites corriges : test_qa.py::_ConcurrencyBackend (expected=2 et 1), test_vision.py::ConcurrencyTracker (expected=3 et 4), test_transcribe.py::ConcurrencyTracker (expected=3 et 4). Aucun test supprime ni saute.
