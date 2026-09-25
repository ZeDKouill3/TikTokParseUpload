---
id: LOG-3bb8f939e82e
type: log
title: "Ajout numpy, scenedetect[opencv], faster-whisper dans dependencies (pyproject.toml). Verifie:"
created: 2026-09-25T11:28:01Z
author: w-4d00
scope:
  - pyproject.toml
about: TASK-4d00da61022c
seq: 2
schema: 4
version: 1
---

 import ModuleNotFoundError avant edit (red), uv pip install -e .[test] OK sans torch, import numpy/scenedetect/cv2/faster_whisper exit 0, pytest -q 118 passed (green). Warning uv 'scenedetect ne definit pas extra opencv' est inoffensif : opencv-python est installe via la resolution normale et cv2 s'importe.
