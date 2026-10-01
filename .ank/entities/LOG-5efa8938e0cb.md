---
id: LOG-5efa8938e0cb
type: log
title: "Lacune design (hors scope, worker.py deja merge TASK-bbe4) : worker.Worker.cancel() termine"
created: 2026-10-01T07:38:25Z
author: w-09fb94c8a7e8
scope:
  - clipper/web/app.py
  - clipper/web/__init__.py
  - tests/test_web.py
about: TASK-09fb94c8a7e8
seq: 2
schema: 4
version: 1
---

 self._process, suppose la meme instance Worker qui a lance l'enfant. L'API web (processus serveur separe) instancie un Worker() frais pour appeler .cancel(video_id) (clause 2, criterion mocke Worker.cancel) : en reel, cross-process, self._process serait None -> crash. Pas corrige ici (hors scope clipper/web). A traiter dans une tache worker/cancel cross-process (pid-based).
