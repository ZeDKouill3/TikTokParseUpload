---
id: LOG-cb282ea46edf
type: log
title: Passage reel complet (CLIPPER_CLAUDE_INTEGRATION=1 pytest tests/integration/test_smoke_real.py -k
created: 2026-09-30T07:57:01Z
author: w-8bf6bff96afb
scope:
  - tests/integration/test_smoke_real.py
  - tests/integration/__init__.py
  - tests/test_smoke_coverage.py
  - docs/GUIDE.md
about: TASK-8bf6bff96afb
seq: 3
schema: 4
version: 1
---

 'not mini_video', 2 lancements : 1 echec local puis correction) : 14/14 usages OK, cout total $0.594 (< $1 vise), duree cumulee des appels API ~82s. Detail (usage: modele, cout USD, duree s) : vocab sonnet 0.0103 4.2s ; transcript_fix sonnet 0.0113 3.7s ; moments opus 0.0398 5.1s ; jury_retention opus 0.0382 5.5s ; jury_spectateur sonnet 0.0235 9.6s ; jury_avocat opus 0.0158 5.7s ; jury_monteur opus 0.0164 6.0s ; jury_conformite sonnet 0.0118 7.3s ; vision sonnet 0.3493 7.7s (poste le plus cher : image jointe) ; parts opus 0.0321 6.0s ; captions sonnet 0.0054 6.7s ; layout sonnet 0.0144 3.8s ; emphasis sonnet 0.0102 3.9s ; qa sonnet 0.0155 6.7s. Aucune erreur d'API (pas de 400 cache_control : jury_spectateur/TASK-f89f n'est pas reproduit ici, un seul tour de 2 candidats ne monte pas a 5 blocs cache_control). Bug trouve et corrige en route : mon moment de test captions n'avait pas de cle 'duration' dans parts[] (KeyError cote test, pas cote clipper.captions) -- corrige. Suite complete verte : 978 passed, 24 skipped. Option mini-video non lancee (pas de CLIPPER_SMOKE_VIDEO disponible dans ce worktree, pas de workspace/ pre-existant) : le test existe et est correctement saute.
