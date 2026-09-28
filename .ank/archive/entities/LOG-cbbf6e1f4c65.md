---
id: LOG-cbbf6e1f4c65
type: log
title: "Clauses: C1 run enchaine les 12 etapes ; C2 saute le fait (2e run : aucun appel LLM, whisper non"
created: 2026-09-25T14:34:43Z
author: w-66a3
scope:
  - clipper/pipeline.py
  - clipper/__main__.py
  - tests/test_pipeline.py
about: TASK-66a381ae40ed
seq: 2
schema: 4
version: 1
---

 recharge) ; C3 review s'arrete apres moments+parts (awaiting_review), decisions via clipper.pipeline.decide -> feedback.record + workspace/<id>/review.json ; C4 'render <id>' reprend, refuse s'il manque des decisions ; C5 auto va au bout, erreur transitoire -> status queued + retry_at, 'queue' reprend apres delai, max_attempts -> failed ; C6 etat workspace/<id>/pipeline.json (pending|running|done|failed + reason) ; C7 e2e video synthetique ffmpeg + FakeBackend + whisper simule -> mp4 + JSON SPEC-350f, qa.is_ready. Lecture prise : reframe tourne avant subtitles (subtitles a besoin d'avoid_zone deduit de reframe/<clip>.json), l'ordre du critere est la liste des etapes, pas un ordre d'execution strict. vision puis moments relance (force) si vision.json plus recent que moments.json.
