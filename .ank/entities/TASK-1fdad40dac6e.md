---
id: TASK-1fdad40dac6e
type: task
slug: tape-audio-courbe-d-nergie-et-pics
title: "Étape audio : courbe d'énergie et pics"
created: 2026-09-25T09:39:39Z
author: claude-plan
status: done
scope:
  - clipper/audio.py
  - tests/test_audio.py
blocked_by: [TASK-4ca09185579f, TASK-4d00da61022c]
done_criteria: |
  L'étape produit workspace/<video_id>/audio.json : énergie RMS en dB par fenêtre de 1 s et liste de pics (timecode, intensité relative à la médiane glissante) ; testé sur un signal synthétique contenant des bursts connus : les pics sont trouvés à +/-1 s.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/f7b6ebd41cc5@615afdc
    tree: scope/78e2d829e482
    criteria: 1a2bae03d244
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---
