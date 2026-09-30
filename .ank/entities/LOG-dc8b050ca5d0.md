---
id: LOG-dc8b050ca5d0
type: log
title: "clipper.moments : ajoute log INFO resume (candidats notes/retenus/rejetes+raisons) et, en selection"
created: 2026-09-30T11:02:11Z
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
seq: 4
schema: 4
version: 1
---

 jury, une ligne par candidat juge (score final -> retenu/rejete/veto/exploration). test_moments.py et test_jury.py toujours verts (pas de regression).
