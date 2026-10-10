---
id: LOG-73ea0fd884d7
type: log
title: "Fix : _stable_face_over_null renvoie (None, stables) sans erreur quand >1 stable et <=1 periode"
created: 2026-10-10T10:28:08Z
author: w-c5b2e09ab02e
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
about: TASK-c5b2e09ab02e
seq: 3
schema: 4
version: 1
---

 avec candidats ; warning + reason journalisent 'une seule periode, persistance non prouvee, Claude fait foi'. Test rouge vu avant fix (ReframeError [2,3]), vert apres ; multi-periodes persistants toujours en erreur (test ajoute). Cause (a) : lead detecte sur 3 faux grands visages de l'ecran d'attente, non corrigee (hors garde-fou, chaque periode echantillonne bien sa plage).
