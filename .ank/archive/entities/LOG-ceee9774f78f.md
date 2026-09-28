---
id: LOG-ceee9774f78f
type: log
title: "Clauses: (1) images de scenes.json dans [start-10,end+10] des candidats de moments.json (moments +"
created: 2026-09-25T13:43:36Z
author: w-7632
scope:
  - clipper/vision.py
  - tests/test_vision.py
about: TASK-7632e278c0ac
seq: 2
schema: 4
version: 1
---

 rejected, tous ont ete candidats) ; (2) decrites via llm.ask usage vision, images jointes, par lots (batch_size) ; (3) vision.json {frames:[{timecode,description,tags,striking}]} : tags du critere + striking lu par moments ; (4) moments relance avec force + vision.json -> note emotion change (fake) ; (5) aucune image hors fenetre envoyee. Lecture : vision ne relance pas moments (ADR-b16b), c'est le pipeline ; le test enchaine moments->vision->moments.
