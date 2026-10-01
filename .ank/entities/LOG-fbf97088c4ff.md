---
id: LOG-fbf97088c4ff
type: log
title: TestClient (httpx ASGITransport) de ce venv bloque indefiniment sur un flux SSE infini (reproduit
created: 2026-10-01T07:38:18Z
author: w-09fb94c8a7e8
scope:
  - clipper/web/app.py
  - clipper/web/__init__.py
  - tests/test_web.py
about: TASK-09fb94c8a7e8
seq: 1
schema: 4
version: 1
---

 hors pytest avec un generateur minimal) : clause 4 testee directement sur le generateur _event_stream (asyncio.wait_for), route verifiee separement sans lire le corps. ADR-4f6e §1 : POST /api/videos et POST /api/videos/{id}/render (v1) lancaient pipeline.run/render en in-process (BackgroundTasks), ce qui viole la contrainte maintenant ratifiee ; corrige pour passer par worker.enqueue (tests mis a jour).
