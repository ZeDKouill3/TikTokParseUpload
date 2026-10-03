---
id: LOG-65aeb34f8f20
type: log
title: "ank done #1 refusé : 1 seul échec dans la suite, tests/test_transcribe.py::test_fix_chunk_result_is_"
created: 2026-10-03T19:20:04Z
author: w-4c3d725175a8
scope:
  - clipper/publish.py
  - clipper/web/app.py
  - clipper/channel.py
  - clipper/pipeline.py
  - clipper/web/static/**
  - tests/test_publish.py
  - tests/test_web.py
  - tests/test_channel.py
  - tests/test_pipeline.py
about: TASK-4c3d725175a8
seq: 5
schema: 4
version: 1
---

cached_and_a_retried_pass_only_recalls_the_missing_chunk (.pytest_cache lastfailed). Hors périmètre, aucun fichier transcribe touché (git diff vide). Mesure : seul -n0 1/1 passe ; fichier entier avec xdist : 1 échec sur 3 puis 1 sur 2 (assert {'mot0':1,..,'mot2':2} == {..,'mot3':1} ligne 1190 : mot3 jamais rappelé) -> test instable préexistant (course). Mes modules : 781 + 516 + 250 tests verts. Relance unique d'ank done.
