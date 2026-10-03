---
id: LOG-74b37c1ddaec
type: log
title: "Backend : /api/publish prend range=day|week|month (422 sinon), bornes calculees en Python"
created: 2026-10-03T22:50:29Z
author: w-ad4dfcebc0c6
scope:
  - clipper/web/app.py
  - clipper/web/static/screens/publish.js
  - clipper/web/static/style.css
  - tests/test_web.py
about: TASK-ad4dfcebc0c6
seq: 1
schema: 4
version: 1
---

 (Europe/Paris ou tz du compte), regroupement days[] par jour sans perte meme minute ; week= reste l'ancre (comportement par defaut inchange, alias week_start/week_end). 5 tests ajoutes, 59 tests publish verts. Reste : JS (selecteur de vue, boites par jour, mise a l'echelle, vue Jour) + CSS.
