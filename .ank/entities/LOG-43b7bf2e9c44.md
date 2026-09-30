---
id: LOG-43b7bf2e9c44
type: log
title: "SPEC-76dc : agencement split implemente dans reframe.py (stream_variant config,"
created: 2026-09-30T14:48:58Z
author: w-b44e504d655b
scope:
  - clipper/reframe.py
  - clipper/render.py
  - clipper/subtitles.py
  - clipper/pipeline.py
  - clipper/assets
  - tests/test_reframe.py
  - tests/test_render.py
  - tests/test_subtitles.py
  - docs/GUIDE.md
  - config.example.toml
about: TASK-b44e504d655b
seq: 2
schema: 4
version: 1
---

 split_webcam_dest/split_gameplay_dest/badge_dest/split_subtitle_dest, validation geometrie au chargement, crop-not-stretch via _crop_to_ratio, exclusion de la webcam pour le jeu avec repli centre note). Decision : title_enabled (render) N'EST PAS lu par reframe.py (ADR-b16b, une etape ne lit pas la config d'une autre) -- reframe fournit la zone title uniquement quand geometriquement possible (place au-dessus de la webcam), l'omet sinon sans erreur ; c'est render.py qui exigera une erreur explicite s'il doit dessiner un titre sans zone. Reste a faire : render.py (title_enabled, badge_*), subtitles.py (style split), pipeline.py (dispatch), tests, GUIDE, config.example.toml, controle reel madajel.
