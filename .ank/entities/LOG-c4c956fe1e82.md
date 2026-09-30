---
id: LOG-c4c956fe1e82
type: log
title: "Reproduction : python -m pytest -q --durations=30 serial = 1166 passed, 25 skipped, 275.64s."
created: 2026-09-30T19:27:01Z
author: w-42a46cb23f78
scope:
  - pyproject.toml
  - tests/conftest.py
about: TASK-42a46cb23f78
seq: 2
schema: 4
version: 1
---

 Collecte seule (--collect-only) = 1.31s pour 1191 tests : imports lourds (cv2/mediapipe/faster_whisper) ecartes comme cause (hypothese refutee par mesure). Top30 durations = ~106s sur 275s : pas un outlier isole, charge CPU repartie sur ~1136 tests a ~0.15s chacun en moyenne (calcul pixel reel : Sobel, imread, cvtColor, resize dans clipper.reframe/vision/qa, pas des mocks).
