---
id: LOG-0b39f94b2e9e
type: log
title: "clipper.vision : progression par lot (INFO throttle 30s/10%, DEBUG chaque lot terminé). Piege"
created: 2026-09-30T11:06:33Z
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
seq: 5
schema: 4
version: 1
---

 trouvé en verifiant test_vision.py au complet : passer de futures[] sequentiels a as_completed() rend l'erreur levee non deterministe (un lot plus petit peut echouer avant le lot 0, changeant le message d'erreur remonte). Corrige en gardant une erreur deterministe (plus petit indice de lot soumis) meme avec as_completed, comme le fait deja clipper.qa. Lecon : toujours relancer la suite complete du module touche, pas seulement le nouveau test cible.
