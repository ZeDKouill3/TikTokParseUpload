---
id: LOG-0564f9edff75
type: log
title: Pipeline + CLI ecrits, 12 tests verts ; mutations (pas de relance moments apres vision, pas de
created: 2026-09-25T14:45:03Z
author: w-66a3
scope:
  - clipper/pipeline.py
  - clipper/__main__.py
  - tests/test_pipeline.py
about: TASK-66a381ae40ed
seq: 3
schema: 4
version: 1
---

 file, pas de controle des decisions, pas d'exemples feedback) chacune detectee. Trouve en relecture : en review, relancer run sur une video terminee la repassait en awaiting_review ; test de regression rouge puis corrige (on ne s'arrete plus si captions est deja fait et tout est decide). Choix : en review une erreur transitoire donne failed (la file d'attente est propre au mode auto, ADR-ad2e).
