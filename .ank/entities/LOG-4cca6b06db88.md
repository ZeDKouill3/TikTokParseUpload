---
id: LOG-4cca6b06db88
type: log
title: "clipper.__main__ : -v/--verbose devient action=count (0=WARNING, 1=INFO, 2+=DEBUG), remplace"
created: 2026-09-30T11:17:20Z
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
seq: 8
schema: 4
version: 1
---

 l'ancien store_true (INFO/WARNING seulement). test_cli.py/test_cli_progress.py toujours verts (progression console par print, independante de logging, non touchee). 20/20 clauses de tests/test_logging_verbose.py vertes. Reste : docs/GUIDE.md, relecture finale, ank done.
