---
id: LOG-c2d9a71f81f2
type: log
title: "TDD : test_captions.py reecrit pour SPEC-6a86 (aucun emoji par defaut, mots interdits ton sobre,"
created: 2026-09-30T12:28:09Z
author: w-ab03e090436c
scope:
  - clipper/captions.py
  - clipper/qa.py
  - tests/test_captions.py
  - tests/test_qa.py
  - docs/GUIDE.md
  - config.example.toml
  - clipper/assets/config.example.toml
about: TASK-ab03e090436c
seq: 3
schema: 4
version: 1
---

 option screen_title_allow_emoji). Implementation clipper/captions.py : CONFIG_DEFAULTS +screen_title_allow_emoji/+screen_title_forbidden_words, _validate_screen_title_emoji inverse (refuse tout emoji par defaut, au plus un si autorise, ZWJ/drapeau toujours refuses), _validate_screen_title_forbidden_words (normalisation accents/casse, mot entier), prompt reecrit (citation ou fait concret, regle emoji/mots interdits explicite). 63/63 tests/test_captions.py verts.
