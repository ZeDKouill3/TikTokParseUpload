---
id: LOG-3cb4e52dd96f
type: log
title: "Clauses (1), (4), (5) vertes : worker.cancel module (kill par pid, raison gardée par le vrai"
created: 2026-10-03T16:22:11Z
author: w-245637313c33
scope:
  - clipper/worker.py
  - clipper/web/app.py
  - clipper/browser.py
  - clipper/tiktok.py
  - clipper/youtube.py
  - clipper/publish.py
  - tests/test_worker.py
  - tests/test_web.py
  - tests/test_browser.py
  - tests/test_tiktok.py
  - tests/test_youtube.py
  - tests/test_publish.py
about: TASK-245637313c33
seq: 3
schema: 4
version: 1
---

 worker), Worker.startup() appelé par loop(), mark_in_progress(expected=) refus -> non pilotée sans échec, partie N-1 non publiée -> attente. Anciens tests Worker.cancel réécrits (cancel module ; escalade kill testée avec _pid_alive/os.kill simulés, Windows ne permet pas un processus qui ignore SIGTERM). Tests 'part_two_goes' verts dès le départ (garde-fous du cas permis).
