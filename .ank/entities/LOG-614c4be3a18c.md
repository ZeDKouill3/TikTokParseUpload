---
id: LOG-614c4be3a18c
type: log
title: "Verrou: link_posts (tout le corps) et la maj last_run de link_if_due sous"
created: 2026-10-07T12:06:32Z
author: w-7136
scope:
  - clipper/learning.py
  - clipper/jury_calibration.py
  - clipper/worker.py
  - tests/test_learning.py
  - tests/test_jury_calibration.py
  - tests/test_worker.py
about: TASK-7136ef90f0b4
seq: 2
schema: 4
version: 1
---

 channel.file_lock(links.json). Test rouge (PermissionError, 4 threads) -> vert. Reproduit le bug des workers concurrents.
