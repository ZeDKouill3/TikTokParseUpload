---
id: LOG-5ac90dbfd8c7
type: log
title: "Désinstallation finale du vrai passage (tentative 5) refusée par Desinstaller.bat : une console"
created: 2026-10-04T01:03:16Z
author: w-a093c293ea3f
scope:
  - tests/test_installer_real.py
  - installer/**
  - AGENTS.md
  - tests/test_installer.py
about: TASK-a093c293ea3f
seq: 12
schema: 4
version: 1
---

 Clipper écoutait réellement sur le port 8000 (process du dépôt principal, pas un artefact de mon test) -- comportement attendu de R8 (jamais désinstaller sous une console active), pas un bug.
