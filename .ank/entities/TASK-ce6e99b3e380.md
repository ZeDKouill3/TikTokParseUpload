---
id: TASK-ce6e99b3e380
type: task
slug: subtitles-g-n-rer-les-sous-titres-des-clips-en-p
title: "subtitles : générer les sous-titres des clips en parallèle"
created: 2026-09-29T08:15:06Z
author: orch-main
status: done
scope:
  - clipper/pipeline.py
  - clipper/subtitles.py
  - tests/test_pipeline.py
  - tests/test_subtitles.py
blocked_by: []
done_criteria: |
  Constaté 2026-09-29 sur ivl0nxa3C7o : l'étape subtitles a pris 120 s pour 22 clips, clipper.pipeline appelant subtitles.generate clip par clip (un llm.ask d'emphase par clip). Attendu : l'étape subtitles de clipper.pipeline génère les clips en parallèle, au plus `parallel` à la fois (nouvelle clé de CONFIG_DEFAULTS de subtitles, défaut 4, lue par le pipeline dans config.section("subtitles") ; 1 = comportement séquentiel actuel ; valeur < 1 refusée avec une erreur explicite ; subtitles.generate ne reçoit pas cette clé et reste utilisable seul). Zones (letterbox ou avoid/reserved) calculées comme aujourd'hui pour chaque clip. Échec d'un clip : les autres clips en cours vont au bout (leurs fichiers restent écrits, un relancement les saute), puis l'erreur remonte et l'étape est en échec (ADR-ad2e). Seule l'étape subtitles change : reframe et render restent séquentiels (GPU/NVENC, ADR-fb9b). Tests (FakeBackend, sans réseau, sans GPU) : avec parallel=4 et un backend qui compte les appels simultanés, au moins 2 appels d'emphase se chevauchent ; avec parallel=1 jamais ; fichiers de sous-titres identiques entre parallel=1 et parallel=4 ; un clip en échec fait échouer l'étape alors que les autres clips sont écrits ; parallel=0 refusé. Toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/a27485e0b942@049f2fa
    tree: scope/8ee60293d1c0
    criteria: 7a123859f45c
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
