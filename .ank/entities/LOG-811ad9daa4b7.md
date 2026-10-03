---
id: LOG-811ad9daa4b7
type: log
title: "Clauses: (1) worker.cancel(video_id, config=) module-level, tue le pid lu dans la file (pas de"
created: 2026-10-03T16:12:32Z
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
seq: 2
schema: 4
version: 1
---

 Worker côté web), pipeline.json failed 'annulée', entrée de file retirée, publications non touchées ; Worker.startup() = orphelins + publications interrompues + migration, appelé par loop() seulement. (2) verrou fichier state/pilot.lock (+ state/pilot.json = compte piloté), attente bornée pilot_wait_s, threading.Lock gardé en plus pour les fils d'un même processus. (3) config passé à open_profile via functools.partial quand opener=None (tiktok publish/fetch_stats, youtube publish/verify_login, export_cookies). (4) mark_in_progress(expected=snapshot) : exige scheduled, pas d'in_progress_since, mêmes compte/slot_at/publish_mode/post_options ; refus -> le worker ne pilote pas et ne marque pas failed. (5) partie N>1 : la N-1 (même series_id) doit être published, et si scheduled_on_* sa date <= date visée ; sinon _wait 'partie N-1 non publiée' (N-1 = numéro).
