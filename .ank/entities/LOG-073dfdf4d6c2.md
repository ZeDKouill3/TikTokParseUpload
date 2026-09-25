---
id: LOG-073dfdf4d6c2
type: log
title: "Implemente clipper/render.py (TDD) : filtergraph ffmpeg (crop/scale par plan/panneau, pile"
created: 2026-09-25T14:15:34Z
author: w-7291
scope:
  - clipper/render.py
  - tests/test_render.py
about: TASK-7291d843d843
seq: 2
schema: 4
version: 1
---

 facecam_gameplay, fallback_blur via boxblur, concat des plans), ass+fontsdir relatif (chemins jamais absolus dans le filtre : colon echappe si cross-drive, decouvert via pytest tmp_path sur C: vs repo sur E:), drawtext hook 2s + Part N/M via fichiers texte temporaires, loudnorm -14 LUFS, encodeur h264_nvenc/libx264 via clipper.gpu. 26 tests dans tests/test_render.py (unitaires sur le filtergraph + integration ffmpeg/ffprobe reelle, forcee CPU via fake_ctranslate2). Suite complete du depot verte (352 passed, 5 skipped).
