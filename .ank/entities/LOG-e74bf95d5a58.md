---
id: LOG-e74bf95d5a58
type: log
title: "Clause 3: test ajoute retire (89 collectes avant/apres). Cache make_mp4 + fixture session"
created: 2026-10-08T20:44:50Z
author: w-8f7cf96b0812
scope:
  - tests/test_qa.py
  - tests/test_packaging.py
  - tests/conftest.py
  - pyproject.toml
about: TASK-8f7cf96b0812
seq: 3
schema: 4
version: 1
---

 built_wheel. Mesure ffmpeg 253->203 et uv build 4->1 par process (plugin de comptage hors repo, scratchpad). Durees -n 4 qa+packaging: 59.0 s -> 52.7 s (une passe chacune). -n 8 non mesure : -n 6 conserve, commentaire pyproject.
