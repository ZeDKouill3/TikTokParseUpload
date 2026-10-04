---
id: LOG-1f2aabcfe21e
type: log
title: "Test reel : le controle 'clipper doctor' post-installation (R10, verifie la composition du PATH du"
created: 2026-10-04T02:11:27Z
author: w-4f1d7d1ee341
scope:
  - installer/**
  - tools/build_portable.py
  - tests/test_build_portable.py
  - tests/test_installer.py
  - tests/test_installer_real.py
  - docs/INSTALLATION.md
  - tests/test_docs_installation.py
about: TASK-4f1d7d1ee341
seq: 7
schema: 4
version: 1
---

 lanceur) utilisait par erreur le PATH reduit (System32 seul) comme base -- ce PATH reduit est correct pour les .bat (C1/C2, prouver qu'ils ne dependent pas du PATH du PC de dev), mais faux ici : un Clipper.bat reel tourne dans un process frais qui a le PATH utilisateur a jour (claude y compris, poste par son installeur officiel). Remis a dict(os.environ) comme base, ffmpeg/venv prepends inchanges.
