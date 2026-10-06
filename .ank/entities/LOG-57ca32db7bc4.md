---
id: LOG-57ca32db7bc4
type: log
title: "Fait : decide/run_if_due/clip/ignore/select_best/restore dans veille.py, hook worker"
created: 2026-10-06T12:57:04Z
author: w-3225a4f9df8c
scope:
  - clipper/veille.py
  - clipper/worker.py
  - clipper/llm/__init__.py
  - tests/test_veille*.py
  - tests/test_worker*.py
  - tests/test_llm.py
about: TASK-3225a4f9df8c
seq: 1
schema: 4
version: 1
---

 (veille_collectors, select_best apres enfant), usage llm veille=strong. Ajout hors SPEC R6 : chaque proposition porte un instantané 'candidate' (affichage apres mise en file, TASK-68b0). Aucun amendement ADR/SPEC requis.
