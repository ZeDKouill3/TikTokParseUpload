---
id: LOG-b45d7efe1b51
type: log
title: Repro reelle sur RTX 3050 (nvidia-cublas-cu12/nvidia-cudnn-cu12 installes temporairement, hors
created: 2026-09-25T16:32:40Z
author: w-f6c8
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
about: TASK-f6c8737af779
seq: 2
schema: 4
version: 1
---

 pyproject) : WhisperModel(device='cuda') se construit sans erreur, mais model.transcribe() leve 'Library cublas64_12.dll is not found or cannot be loaded'. Hypothese 1 (os.add_dll_directory sur nvidia/*/bin) : mesuree fausse -- ctypes.WinDLL('cublas64_12.dll') charge bien apres add_dll_directory, mais faster-whisper/CTranslate2 echoue quand meme au meme endroit (delay-load interne qui ne respecte pas AddDllDirectory). Hypothese 2 (prefixer os.environ['PATH'] avec les dossiers bin nvidia avant le chargement) : mesuree vraie -- meme script, PATH modifie a la place, transcribe() reussit. Fix : prefixer PATH (jamais add_dll_directory seul).
