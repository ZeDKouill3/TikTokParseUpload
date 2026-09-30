---
id: LOG-beeb2b134643
type: log
title: "Instrumentation : profilage cProfile d'un test isole"
created: 2026-09-30T19:27:17Z
author: w-42a46cb23f78
scope:
  - pyproject.toml
  - tests/conftest.py
about: TASK-42a46cb23f78
seq: 3
schema: 4
version: 1
---

 (test_split_reframe_cached_with_a_different_stream_variant_is_an_error_without_force) confirme un cout CPU reel (pas de fixture a mutualiser) : _edge_mask/Sobel 2.86s+1.41s, imread 2.62s, write_frame (fixture numpy+imencode) 2.73s, astype 0.99s. cv2.getNumThreads() = 12 par defaut (= coeurs logiques) : sous pytest-xdist, chaque worker relance jusqu'a 12 threads OpenCV internes -> N workers x 12 threads sature largement une machine a 12 coeurs logiques. Hypothese : c'est cette double-sursouscription (process xdist x threads OpenCV), pas le nombre de workers en soi, qui degrade le passage a l'echelle ET rend flaky les tests bases sur un vrai chrono (ConcurrencyTracker dans test_vision.py/test_qa.py/test_transcribe.py, hors scope) en privant leurs threads Python de CPU. Verifie : avant fix, -n auto a produit 1 a 3 echecs flaky sur ces tests selon les runs (ex. test_vision.py::test_parallel_defaults_to_four: assert 3 == 4). Apres cv2.setNumThreads(1) dans tests/conftest.py (code CPU oversubscription, une ligne, deja dans le scope conftest.py) : run complet avec -n auto = 1166 passed, 25 skipped (identique au baseline), 0 echec, 180.66s.
