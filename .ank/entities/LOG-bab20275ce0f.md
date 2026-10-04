---
id: LOG-bab20275ce0f
type: log
title: Ajouté --sans-raccourci à install.ps1 (tests dry-run verts) ; écrit tests/test_installer_real.py
created: 2026-10-04T00:28:39Z
author: w-a093c293ea3f
scope:
  - tests/test_installer_real.py
  - installer/**
  - AGENTS.md
about: TASK-a093c293ea3f
seq: 4
schema: 4
version: 1
---

 (seul test, skipif CLIPPER_INSTALLER_REAL absent ou powershell/uv absents) ; documenté la commande dans AGENTS.md. Lancement du vrai passage en arrière-plan (build zip, install CPU, doctor, mise à jour, désinstallation) sous research/installer-real/, hors xdist (-p no:xdist) pour ne pas peser sur le CPU pendant que la vidéo tourne sur ce PC.
