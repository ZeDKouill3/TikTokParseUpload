---
id: LOG-fc4e5a9080f4
type: log
title: "Cause : os.replace sans réessai dans Worker._beat ; PermissionError réelle 10/10 12:50 Paris a tué"
created: 2026-10-10T13:39:55Z
author: orch-0dbe
scope:
  - clipper/worker.py
  - tests/test_worker.py
about: TASK-0dbead00e989
seq: 1
schema: 4
version: 1
---

 la boucle. Correctif : channel.replace_retrying, puis battement sauté + warning si le verrou persiste. Tests rouges avant (2), 266 verts après dans test_worker.py.
