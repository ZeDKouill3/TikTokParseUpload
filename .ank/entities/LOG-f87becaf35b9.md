---
id: LOG-f87becaf35b9
type: log
title: 25 tests rouges écrits (test_publish x9, test_pipeline x2, test_web x14), chacun échoue sur le
created: 2026-10-03T19:01:24Z
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
seq: 3
schema: 4
version: 1
---

 symptôme du rapport : set_channel laisse published/rejected dans _sans_chaine (clips 'à valider'); bulk 409 'approbation refusé ... scheduled' au lieu du refus groupé, ou 200 sur failed manual; série p1 published -> 409; approve form-entry accepté; p2 05/10 18:30 < p1 08/10; account_publish_times=[] après suppression du preset; delete invalide 500; mark_published/set_mode acceptés en cours. Choix point 4 : lecteurs (_account_entries/all_entries) parcourent aussi state/publish/*.json au lieu de refuser la suppression (test existant: published ne bloque pas). Point 3/I3 : refus d'approve sur entrée portant manual/publish_mode/post_options.
