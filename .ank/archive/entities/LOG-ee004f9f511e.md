---
id: LOG-ee004f9f511e
type: log
title: mediapipe ajoute dans dependencies ; scenedetect[opencv] -> scenedetect nu car scenedetect 0.7.1
created: 2026-09-25T13:33:38Z
author: w-b817
scope:
  - pyproject.toml
about: TASK-b817ea1319a9
seq: 1
schema: 4
version: 1
---

 exige deja opencv-python en dur (extra opencv n'existe plus). Conflit opencv-python (scenedetect) vs opencv-contrib-python (mediapipe) : exclu opencv-python via [tool.uv] override-dependencies (marker sys_platform=='never'), contrib etant un sur-ensemble qui satisfait cv2 pour les deux. Verifie install propre + imports + pytest (158 passed, 1 skipped) dans un venv 3.11 neuf hors du venv du worker. Telechargement total ~90MB, sous la limite 1Go.
