---
id: LOG-19f8bd94e1dc
type: log
title: "Mesure 2 (lecture seule) sur les 42 dossiers workspace/<id> entiers + racine workspace/ : 17 726"
created: 2026-10-09T12:16:23Z
author: w-8ff9fb648bdd
scope:
  - clipper/web/static/screens/videos.js
  - clipper/web/app.py
  - clipper/workspace.py
  - tests/test_web.py
  - tests/test_workspace.py
  - CHANGELOG.md
about: TASK-8ff9fb648bdd
seq: 6
schema: 4
version: 1
---

 232 894 octets, identiques à l'octet (ancienne et nouvelle, 0 dossier divergent). Dossiers vidéo : ancienne rglob+stat médiane 0,247 s (essais 0,391/0,247/0,238), nouvelle os.scandir médiane 0,027 s (0,027/0,023/0,034). Racine : ancienne médiane 0,382 s, nouvelle 0,027 s. Gain ~9 à 14 fois, même total. Critère (3) : avant = GET console 0,15/0,67/0,97 s ; après = cette mesure Python (validée par l'utilisateur, pas de redémarrage serve).
