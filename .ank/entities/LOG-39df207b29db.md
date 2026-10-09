---
id: LOG-39df207b29db
type: log
title: "red confirme: GetFullPath sur 'C:\\a|b<x>' hors try -> ArgumentException, exit 1 brut. Green:"
created: 2026-10-09T01:45:40Z
author: w-5b006827170f
scope:
  - installer/desinstaller.ps1
  - tests/test_installer.py
  - CHANGELOG.md
about: TASK-5b006827170f
seq: 2
schema: 4
version: 1
---

 normalisation dans try, raison 'champ app illisible (<valeur>)', remede matche *illisible*. Tests pointeur/illisible existants inchangés (verts). Ambiguïté: aucune.
