---
id: LOG-e48b1c9defdd
type: log
title: "parts.py et captions.py : moments traites en parallele (ThreadPoolExecutor, cle [parts]/[captions]"
created: 2026-09-29T08:29:08Z
author: w-ed18b7116308
scope:
  - clipper/parts.py
  - clipper/captions.py
  - tests/test_parts.py
  - tests/test_captions.py
about: TASK-ed18b7116308
seq: 2
schema: 4
version: 1
---

 parallel, defaut 4, refuse < 1) ; dans captions les parties d'un meme moment restent sequentielles. Tests ajoutes (backends de test avec verrou pour mesurer le chevauchement, sortie identique parallel=1/4, echec propage). pytest complet en cours (suite longue, tourne en tache de fond).
