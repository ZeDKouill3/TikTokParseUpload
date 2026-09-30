---
id: LOG-df995c06aad6
type: log
title: "subtitles.py : style split ajoute (generate(style='split')), refactor"
created: 2026-09-30T14:58:53Z
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
seq: 3
schema: 4
version: 1
---

 _Box/_layout/_place/_render_letterbox en _render_positioned parametre par _Style (letterbox et split partagent le meme moteur de mise en page/paliers). Couleurs split_* au format amical (#RRGGBB ou nom) converties via _ass_color, jamais le format ASS natif directement. Chaque mot est son propre 'mot en cours' (emphasis=tous les indices), jamais d'appel LLM. Ombre approx via Shadow=moyenne(|dx|,|dy|) + BackColour (ASS n'a pas d'offset x/y separe). 15 nouveaux tests, suite complete verte (77 passed). Reste : render.py (title_enabled, badge_*, dispatch stream_split), pipeline.py (style split pour subtitles_clip), GUIDE, config.example.toml, controle reel madajel.
