---
id: LOG-fa04f87c5dce
type: log
title: "clipper.pipeline : ajoute duree de chaque etape (etape %s terminee en Xs), progression clip i/N"
created: 2026-09-30T10:59:45Z
author: w-8abc2ab932e9
scope:
  - clipper/pipeline.py
  - clipper/__main__.py
  - clipper/transcribe.py
  - clipper/moments.py
  - clipper/jury.py
  - clipper/vision.py
  - clipper/parts.py
  - clipper/captions.py
  - clipper/reframe.py
  - clipper/subtitles.py
  - clipper/render.py
  - clipper/qa.py
  - clipper/download.py
  - clipper/audio.py
  - clipper/llm
  - tests/test_logging_verbose.py
  - docs/GUIDE.md
about: TASK-8abc2ab932e9
seq: 3
schema: 4
version: 1
---

 (reframe/render, INFO throttle 30s/10%, DEBUG chaque clip), et resume final a la fin d'un run reussi (duree par etape, nb clips, statuts qa, cout LLM total+par usage, chemin de sortie). 9 tests verts (tests/test_logging_verbose.py).
