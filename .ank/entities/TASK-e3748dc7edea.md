---
id: TASK-e3748dc7edea
type: task
slug: tape-scenes-changements-de-plan-et-images-cl-s
title: "Étape scenes : changements de plan et images clés"
created: 2026-09-25T09:39:38Z
author: claude-plan
status: done
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
blocked_by: [TASK-4ca09185579f, TASK-4d00da61022c]
done_criteria: |
  L'étape produit workspace/<video_id>/scenes.json (plans {start, end}) via PySceneDetect et extrait une image clé par plan plus une toutes les N secondes (N en config) dans les plans plus longs que N, en JPEG sous workspace/<video_id>/frames/ avec leur timecode dans le JSON ; testé sur une vidéo synthétique générée par ffmpeg (aplats de couleur qui changent) : le nombre de plans détectés est le bon.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/ef30e59d2a8b@615afdc
    tree: scope/e14db3f6006d
    criteria: f59ce4053c9c
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---
