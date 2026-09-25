---
id: TASK-c2dc0b12c3a2
type: task
slug: render-fond-flou-rapide-r-duire-flouter-agrandir
title: "render : fond flou rapide (réduire, flouter, agrandir)"
created: 2026-09-25T19:51:10Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/render.py
  - tests/test_render.py
blocked_by: []
done_criteria: |
  Constat essai réel 2026-09-25 : les clips en fallback_blur prennent 4 à 5 min de rendu (ffmpeg ~1200 s CPU pour 40 s) contre ~45 s sans flou, à cause du flou plein cadre 1080x1920 sur CPU. Le fond flou est calculé à résolution réduite (facteur configurable, défaut 1/4) puis agrandi, pour un rendu visuellement équivalent ; test : rendu d'une vidéo synthétique en fallback_blur au moins 3 fois plus rapide qu'avant à paramètres égaux (mesuré dans le test sur une courte vidéo), sortie toujours conforme (1080x1920, 30 i/s, h264, aac) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
