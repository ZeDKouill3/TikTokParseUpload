---
id: LOG-7a62c49c3e8e
type: log
title: jury.py ne peut pas importer clipper.jury_calibration (test_jury verrouille ses imports a
created: 2026-09-25T19:13:02Z
author: w-15c1
scope:
  - clipper/jury.py
  - clipper/jury_calibration.py
  - tests/test_jury_calibration.py
about: TASK-15c12de2d29f
seq: 3
schema: 4
version: 1
---

 llm/config) : jury lit lui-meme le fichier via config.section('jury_calibration')['weights_path'] ; mediane ponderee par critere, 1 pour un juge absent du fichier, JuryError si fichier illisible ou si conformite/juge a veto != 1. Mediane ponderee = statistics.median a poids egaux (moitie pile sur frontiere -> moyenne). Risque note : tests/test_jury.py ne tourne pas en isolated_cwd ; un state/jury_weights.json reel a la racine ou pytest est lance changerait ses medianes (hors scope, a traiter dans test_jury si besoin).
