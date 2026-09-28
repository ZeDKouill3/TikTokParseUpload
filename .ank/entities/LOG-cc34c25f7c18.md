---
id: LOG-cc34c25f7c18
type: log
title: "Reproduit numeriquement : _floor1(2428.54)=2428.5 < fin du connecteur 2428.54, la borne publiee"
created: 2026-09-28T20:56:58Z
author: w-3c0a
scope:
  - clipper/moments.py
  - tests/test_moments.py
  - clipper/subtitles.py
  - tests/test_subtitles.py
about: TASK-3c0ada196d80
seq: 4
schema: 4
version: 1
---

 recule dans le mot retire (bug ADR/regle 5). Hypothese : precision tenth + floor pour start est la cause ; regle 5 (SPEC-1557 v2) exige centieme et start ne doit jamais reculer. Fix prevu : fonction _round2 (ceil, hundredth) pour start/end publies (_public, _judge veto, _restore, _rescore) ; _span (affichage prompt) et parts[] (hors scope, clipper/parts.py) laisses en dixieme.
