---
id: LOG-9a3e3a7204de
type: log
title: "Scope amendé (+clipper/journal.py) : la clause (5) exige que journal.mask_secrets masque"
created: 2026-10-06T13:22:20Z
author: w-68b0b5cdd940
scope:
  - clipper/web/**
  - tests/test_web*.py
  - CHANGELOG.md
  - docs/GUIDE.md
  - clipper/journal.py
about: TASK-68b0b5cdd940
seq: 3
schema: 4
version: 1
---

 twitch_client_secret/youtube_api_key, la regex _SECRET_KEY_RE ne les couvre pas. Pas d'assouplissement du critère.
