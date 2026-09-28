---
id: LOG-1f209fe3a5c1
type: log
title: "Rendu reel libass : deux Dialogue simultanes sur le meme layer entrent en collision, libass decale"
created: 2026-09-28T18:23:07Z
author: w-a62e
scope:
  - clipper/subtitles.py
  - tests/test_subtitles.py
  - clipper/pipeline.py
  - tests/test_pipeline.py
about: TASK-a62ee1d6777a
seq: 9
schema: 4
version: 1
---

 la 2e ligne (haut d'encre 1409 au lieu de 1353, bas 1465 > y1 1448). Correctif : layer = rang de la ligne (spec ASS : la detection de collisions ignore les layers differents) ; test ffmpeg vert (ecart 78 +- 4, encre dans la zone). Aussi : la phrase de la maquette fait 8 mots, letterbox_max_words_per_group = 8. Pillow et fontTools ne sont pas declares dans pyproject.toml (installes en dependances transitives) : imports paresseux dans subtitles, la declaration revient a TASK-b7f4 (seul a toucher pyproject).
