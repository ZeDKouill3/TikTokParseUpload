---
id: TASK-66a381ae40ed
type: task
slug: orchestration-pipeline-cli-de-bout-en-bout-modes
title: Orchestration pipeline + CLI de bout en bout, modes review/auto, file d'attente
created: 2026-09-25T09:39:48Z
author: claude-plan
status: done
scope:
  - clipper/pipeline.py
  - clipper/__main__.py
  - tests/test_pipeline.py
blocked_by: [TASK-7291d843d843, TASK-cdc453cd2655, TASK-e116dad45d8f, TASK-7632e278c0ac]
done_criteria: |
  'python -m clipper run <url>' enchaîne download, transcribe, scenes, audio, moments, vision, parts, captions, subtitles, reframe, render, qa en sautant les étapes déjà faites ; en mode review il s'arrête après moments et parts en attente de décisions (enregistrées via feedback) et 'python -m clipper render <video_id>' reprend ; en mode auto il va jusqu'au bout et une erreur transitoire met la vidéo en file d'attente avec re-essai différé ; l'état par étape (pending, running, done, failed + raison) est lisible pour l'interface ; un test de bout en bout sur vidéo synthétique avec backend LLM fake et whisper simulé produit au moins un clip et son JSON valides.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/702504420d3b@002ea72
    tree: scope/fe82ba1d426f
    criteria: f96218a534cb
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Reprend clipper/pipeline.py posé par la tâche squelette.
