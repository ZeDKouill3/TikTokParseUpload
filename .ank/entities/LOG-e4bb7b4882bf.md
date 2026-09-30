---
id: LOG-e4bb7b4882bf
type: log
title: "ank done (1er run) : timeout 900s, contention CPU avec job GPU d'un autre worker sur la meme"
created: 2026-09-30T18:38:44Z
author: w-b6b731ad188a
scope:
  - docs/benchmarks/whisper-modeles.md
  - clipper/transcribe.py
  - tests/test_transcribe.py
  - config.example.toml
about: TASK-b6b731ad188a
seq: 4
schema: 4
version: 1
---

 machine. 2e run : 4 echecs reels (test_cli_init, test_packaging) - clipper/assets/config.example.toml est une copie embarquee (package data pour 'clipper init' installe en wheel) qui doit rester identique a config.example.toml racine, oubliee lors de l'edit. Resynchronisee avec le meme ajout. Verifie cible (tests/test_cli_init.py tests/test_packaging.py) : 17 passed.
