---
id: LOG-26a1f23dd4b3
type: log
title: "Test reel (tests/test_installer_real.py) : 'clipper doctor' appele via subprocess.run(['clipper',"
created: 2026-10-04T02:07:35Z
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
seq: 6
schema: 4
version: 1
---

 'doctor'], env=doctor_env) levait FileNotFoundError (WinError 2) une fois le PATH de env= reduit -- CreateProcess resout un nom non qualifie via le PATH du PROCESS PARENT (le test), pas via le dict env= du sous-processus. Corrige en appelant clipper.exe par son chemin complet (app\.venv\Scripts\clipper.exe), jamais a nu, meme principe que C1/C2 mais applique ici au harnais de test lui-meme.
