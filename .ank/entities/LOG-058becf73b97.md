---
id: LOG-058becf73b97
type: log
title: "red : 3 tests (1 TikTok, 2 YouTube) echouent ; captures ecrites sous state/browser par defaut au"
created: 2026-10-09T00:08:03Z
author: w-89dc7b817484
scope:
  - clipper/tiktok.py
  - clipper/youtube.py
  - tests/test_tiktok.py
  - tests/test_youtube.py
  - CHANGELOG.md
about: TASK-89dc7b817484
seq: 2
schema: 4
version: 1
---

 lieu de [browser] state_dir. Cause : profile_dir(self.account) sans config a tiktok.py:511, youtube.py:205 et :385
