---
id: TASK-c37fa74c63c8
type: task
slug: stabiliser-les-tests-de-concurrence-reelle-concu
title: Stabiliser les tests de concurrence reelle (ConcurrencyTracker) sous execution parallele
created: 2026-09-30T19:33:25Z
author: w-42a46cb23f78
status: closed
scope:
  - tests/test_qa.py
  - tests/test_vision.py
  - tests/test_transcribe.py
blocked_by: []
done_criteria: |
  Diagnostic (ank log): reproduire le flaky observe en lancant plusieurs fois tests/test_qa.py::test_parallel_four_overlaps_llm_calls, tests/test_vision.py::test_parallel_defaults_to_four, tests/test_vision.py::test_batches_run_concurrently_up_to_parallel_setting et tests/test_transcribe.py::test_fix_parallel_defaults_to_config_value_of_four sous pytest-xdist (-n auto, voir pyproject.toml) en presence d'une charge CPU concurrente (ex: un autre processus CPU-bound en tache de fond) ; ces tests utilisent un compteur partage (peak concurrency) mesure via time.sleep(0.05-0.2s) dans un ThreadPoolExecutor, sensible a l'ordonnancement reel quand le CPU est sursouscrit. Correctif: rendre ces tests robustes a la sursouscription CPU (ex: fenetre de mesure plus longue, barriere/Event au lieu d'un sleep fixe, ou tolerance sur le pic mesure) sans changer ce qu'ils verifient (le parallelisme reel est respecte) ; aucune valeur de secours qui masquerait une vraie regression de concurrence. Verifier : ces 4 tests passent de facon repetee (>=20 runs) sous -n auto avec une charge CPU concurrente artificielle, sans regression sur le reste de test_qa.py/test_vision.py/test_transcribe.py.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 2
---

Decouvert en travaillant TASK-42a46cb23f78 (paralleliser la suite via pytest-xdist pour repasser sous 90s). cv2.setNumThreads(1) (voir tests/conftest.py) a deja supprime une bonne partie de la sursouscription (N workers x threads OpenCV), mais un ank done complet a encore vu tests/test_qa.py::test_parallel_four_overlaps_llm_calls echouer une fois sous charge partagee (autres sessions agent actives sur la meme machine). Ces tests de concurrence 'temps reel' restent hors du scope de TASK-42a46cb23f78 (pyproject.toml, tests/conftest.py seulement) : le correctif touche forcement ces fichiers de test eux-memes.
