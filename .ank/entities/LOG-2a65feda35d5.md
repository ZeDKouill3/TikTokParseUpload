---
id: LOG-2a65feda35d5
type: log
title: "I1 ajuste : l'override OpenCV est un fichier statique livre dans le zip (installer/overrides.txt,"
created: 2026-10-04T01:49:34Z
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
seq: 3
schema: 4
version: 1
---

 ajoute a SUBDIR_INSTALLER_FILES dans tools/build_portable.py) plutot que genere a l'installation dans app\cache -- correspond mieux au libelle du critere ('fichier d'overrides livre dans le zip'). docs/INSTALLATION.md (section Mise a jour) mis a jour pour refleter I5 : plus besoin de repeter --app/--data a une relance, l'installeur les retrouve via le pointeur.
