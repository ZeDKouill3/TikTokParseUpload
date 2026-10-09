---
id: LOG-86edcc7951d0
type: log
title: "released: Aucun levier CPU mesuré sur 20 min réels ne tient gain >= 25 % ET >= 95 % des coupes ET"
created: 2026-10-09T11:40:23Z
author: w-ce12e4753cfe
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
  - CHANGELOG.md
about: TASK-ce12e4753cfe
seq: 4
schema: 4
version: 1
---

 <= 5 % de coupes en trop : le décodage ffmpeg sature déjà les 12 coeurs (paralléliser/threads ne gagne rien ou perd, fps bas et -skip_frame changent les coupes). Code inchangé, mesures dans le log de la tâche.
