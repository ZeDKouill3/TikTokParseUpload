---
id: TASK-20f11d2aab66
type: task
slug: tests-la-suite-compl-te-ne-laisse-plus-19-go-sur
title: "Tests : la suite complète ne laisse plus ~19 Go sur C: (vidéos synthétiques des tests de reframe/webcam allégées, rétention des dossiers temporaires pytest limitée)"
created: 2026-10-08T06:56:39Z
author: nicoc@zedk_ordi
status: done
scope:
  - tests/test_reframe.py
  - pyproject.toml
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Constat 08/10 : chaque suite complète laisse ~19 Go dans C:\Users\nicoc\AppData\Local\Temp\pytest-of-nicoc\pytest-N (pytest-1786 18,9 Go, 2229 19,3, 2276 19,3, 2323 19,5) ; dans pytest-2276, les tests de tests/test_reframe.py (test_period_without_webcam..., test_none_answer_gives_no_webc..., test_just_chatting_then_game..., test_each_clip_takes_the_recta..., test_nothing_is_remembered_fro... 1,4 Go) écrivent chacun ~713 Mo ; plusieurs suites simultanées (ank done des workers) ont rempli C: (ENOSPC) le 08/10 vers 08:45. (1) Les vidéos synthétiques de ces tests sont réduites (résolution, durée, cadence, codec compressé au lieu de brut) au minimum qui garde ce que chaque test vérifie : chaque test reframe écrit au plus ~50 Mo (mesuré et noté dans le rapport du worker). (2) pyproject [tool.pytest.ini_options] : tmp_path_retention_policy = "failed" (et tmp_path_retention_count = 1) pour ne garder que les dossiers des tests en échec. (3) Aucun test n'est supprimé ni affaibli : mêmes assertions. (4) Mesure avant/après de la taille du dossier basetemp d'un run de tests/test_reframe.py, dans le rapport du worker et le CHANGELOG [Non publié] (section Interne ou Corrigé).
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/2a8879dfc79d@4140db1
    tree: scope/896e4beb5dbc
    criteria: 49d9a810f280
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
