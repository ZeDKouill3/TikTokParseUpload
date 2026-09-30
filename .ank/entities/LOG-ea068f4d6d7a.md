---
id: LOG-ea068f4d6d7a
type: log
title: "Repro: pytest -k <3 tests> --durations=10 -> 74.78s+47.02s+34.60s (159s total), correspond a"
created: 2026-09-30T08:08:17Z
author: w-cde183a0041f
scope:
  - tests/test_pipeline.py
about: TASK-cde183a0041f
seq: 2
schema: 4
version: 1
---

 l'estimation de la tache (165s/400s). Instrumentation temporaire (time.perf_counter par etape dans pipeline._advance_steps, revertee) sur test_auto seul (61s) : download 0.01s, transcribe 0.76s, scenes 2.33s, audio 0.11s, moments 0.02s, vision 0.11s, parts 0.01s, captions 0.01s, reframe 0.06s, subtitles 0.06s, render 9.78s, qa FAILED(transitoire simule) apres 22.31s, puis qa reel 21.09s. Hypothese : qa.check_clip fait 2 passes cv2 pleine resolution (scan histogrammes HSV + extraction images) + ffmpeg blackdetect + ffprobe sur le mp4 rendu en 1080x1920 (expected_width/height qa, output_width/height reframe) ; render encode aussi ce canevas 1080x1920 (fallback_blur letterbox). Le cout vient de la resolution de sortie du clip, pas de la duree de la video source (scenes sur 80s source ne coute que 2.33s). Correctif prevu : reduire reframe.output_width/output_height et qa.expected_width/expected_height dans la config de ces 3 tests (test-only, CONFIG_DEFAULTS existant, pas de code de prod touche).
