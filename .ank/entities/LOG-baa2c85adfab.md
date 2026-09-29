---
id: LOG-baa2c85adfab
type: log
title: "scope elargi a tests/test_pipeline.py : WhisperFactory.Model (fixture de test_pipeline.py) n'a pas"
created: 2026-09-29T20:24:52Z
author: w-746b5e0ddca7
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
  - tests/test_subtitles.py
  - tests/test_pipeline.py
about: TASK-746b5e0ddca7
seq: 5
schema: 4
version: 1
---

 les attributs du vrai WhisperModel (feature_extractor...), donc le nouveau defaut batch_size=8 (BatchedInferencePipeline reel) casse 8 tests de pipeline complet. Fix prevu : donner a step_options() de test_pipeline.py un pipeline_factory de test qui delegue au faux modele, comme run() dans test_transcribe.py -- ajustement pur de fixture de test, aucun critere assoupli.
