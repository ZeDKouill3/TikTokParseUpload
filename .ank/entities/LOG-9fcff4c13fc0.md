---
id: LOG-9fcff4c13fc0
type: log
title: "impl: qa.run parallel via ThreadPoolExecutor(max_workers=parallel), pending clips soumis en une"
created: 2026-09-29T08:29:54Z
author: w-13660059a1b1
scope:
  - clipper/qa.py
  - tests/test_qa.py
about: TASK-13660059a1b1
seq: 2
schema: 4
version: 1
---

 fois, erreur du premier clip (ordre trie) remontee apres que tout ait fini, _warn_series saute si erreur. config() test aide fixe parallel=1 par defaut pour garder l'ordre deterministe des anciens tests. 54/54 test_qa.py vert.
