---
id: LOG-5d8ab4e7c245
type: log
title: "Pistes ecartees par mesure (criterion nommait les deux) : 'imports lourds differes' inutile ici"
created: 2026-09-30T19:28:10Z
author: w-42a46cb23f78
scope:
  - pyproject.toml
  - tests/conftest.py
about: TASK-42a46cb23f78
seq: 5
schema: 4
version: 1
---

 (collecte = 1.31s pour 1191 tests, pas le goulot) ; 'fixtures couteuses partagees' inapplicable : le cout (Sobel/imread/cvtColor/resize) est le comportement reellement teste avec des specs differentes par test (pas une fixture redondante identique reutilisable). Top5 durations baseline (call, serie) : test_qa.py::test_every_rendered_clip_of_the_video_is_checked 5.02s, test_reframe.py::test_split_reframe_cached_with_a_different_stream_variant_is_an_error_without_force 4.69s, test_pipeline.py::test_auto_runs_every_step_queues_a_transient_error_then_finishes 4.56s, test_reframe.py::test_clip_with_a_live_but_faceless_facecam_stays_stream 4.21s, test_reframe.py::test_split_layout_crops_webcam_and_gameplay_without_deformation 4.12s -- tous du calcul reel, aucun a isoler/sauter. Aucun fichier hors scope (pyproject.toml, tests/conftest.py) n'a du etre touche : le fix cv2.setNumThreads(1) dans conftest.py a supprime la flakiness observee sur les tests de concurrence reelle (test_vision.py, test_qa.py, test_transcribe.py) sans les modifier.
