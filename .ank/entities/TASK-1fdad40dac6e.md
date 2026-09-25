---
id: TASK-1fdad40dac6e
type: task
slug: tape-audio-courbe-d-nergie-et-pics
title: "Étape audio : courbe d'énergie et pics"
created: 2026-09-25T09:39:39Z
author: claude-plan
status: open
scope:
  - clipper/audio.py
  - tests/test_audio.py
blocked_by: [TASK-4ca09185579f]
done_criteria: |
  L'étape produit workspace/<video_id>/audio.json : énergie RMS en dB par fenêtre de 1 s et liste de pics (timecode, intensité relative à la médiane glissante) ; testé sur un signal synthétique contenant des bursts connus : les pics sont trouvés à +/-1 s.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
