---
id: LOG-7f6c8cc08f26
type: log
title: "render.py: source_url du sidecar vient de meta.json/webpage_url (RenderError si absent), jamais"
created: 2026-09-30T09:00:51Z
author: w-9290de6c858c
scope:
  - clipper/download.py
  - clipper/render.py
  - clipper/__main__.py
  - clipper/web/static/index.html
  - tests/test_download.py
  - tests/test_render.py
about: TASK-9290de6c858c
seq: 3
schema: 4
version: 1
---

 reconstruit en YouTube. download.py: webpage_url = info['webpage_url'] ou repli sur l'URL demandee (jamais une URL reconstruite depuis video_id) - corrige une regression sur test_pipeline.py (fake yt-dlp sans webpage_url). Textes d'aide CLI + page web mentionnent Twitch.
