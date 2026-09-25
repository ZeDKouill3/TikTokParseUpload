---
id: TASK-e9cfe6e54ec6
type: task
slug: vision-lots-d-images-en-parall-le-et-reprise-des
title: "vision : lots d'images en parallèle et reprise des lots déjà décrits"
created: 2026-09-25T18:01:41Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/vision.py
  - tests/test_vision.py
blocked_by: []
done_criteria: |
  L'étape vision traite jusqu'à parallel lots en même temps (nouveau réglage de CONFIG_DEFAULTS, défaut 4), chaque lot restant un appel clipper.llm validé contre son schéma ; vision.json est identique à un traitement séquentiel (mêmes descriptions aux mêmes timecodes, ordre par timecode) ; chaque lot réussi est enregistré au fil de l'eau (workspace/<video_id>/vision_partial.json) et une relance après échec ne redemande pas les lots déjà décrits (testé avec FakeBackend qui compte ses appels) ; un lot en échec fait échouer l'étape avec sa raison (ADR-ad2e) ; vision_partial.json est supprimé quand vision.json est écrit ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Essai réel 2026-09-25 (sZi-qJ-5ptA) : 448 images autour de 32 candidats, 56 lots de 8 traités en série, ~1 min par lot, soit ~1 h. Même remède que transcript_fix (TASK-a6d4) : threads, car les appels LLM sont des sous-processus.
