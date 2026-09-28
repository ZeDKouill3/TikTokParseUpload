---
id: LOG-dc0b934ff56c
type: log
title: "mediapipe 1.0.1 installe n'a plus mp.solutions ni modele embarque: FaceDetector (Tasks API) exige"
created: 2026-09-25T13:40:00Z
author: w-85a9
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
about: TASK-85a99afa3206
seq: 4
schema: 4
version: 1
---

 un .tflite. Obtention: reglage model_path (defaut ~/.cache/clipper/blaze_face_short_range.tflite); s'il manque, telechargement unique depuis model_url (storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite) au premier run reel; model_url vide = erreur explicite. Jamais dans les tests par defaut: test reel optionnel saute sauf CLIPPER_REAL_MODELS=1.
