---
id: LOG-8eab3e24e231
type: log
title: "Vrai passage complet par l'orchestrateur sur main 65b56d0, serveur 8000 arrêté :"
created: 2026-10-04T02:38:38Z
author: orch
scope:
  - installer/**
  - tools/build_portable.py
  - tests/test_build_portable.py
  - tests/test_installer.py
  - tests/test_installer_real.py
  - docs/INSTALLATION.md
  - tests/test_docs_installation.py
about: TASK-4f1d7d1ee341
seq: 10
schema: 4
version: 1
---

 CLIPPER_INSTALLER_REAL=1 tests/test_installer_real.py -> 1 passed en 264 s (construction du zip, installation PATH vierge, doctor, mise à jour, désinstallation --donnees).
