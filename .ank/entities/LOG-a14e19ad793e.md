---
id: LOG-a14e19ad793e
type: log
title: "Complement utilisateur (meme tache) : N compte des POSTS (une partie = un post, pas des clips) ;"
created: 2026-10-03T11:19:05Z
author: w-5bbf77badfd0
scope:
  - clipper/publish.py
  - clipper/web/**
  - tests/test_publish.py
  - tests/test_web.py
about: TASK-5bbf77badfd0
seq: 2
schema: 4
version: 1
---

 une serie de parties qui ne tient pas dans les places restantes est sautee entiere (jamais coupee), on prend le clip suivant. Ajout d'un mode Manuel en plus d'Automatique dans le formulaire Programmer une serie : liste des clips disponibles (memes exclusions que l'auto) a cocher, ordre = ordre de selection, reordonnable (monter/descendre) ; cocher une partie ajoute toutes les parties du clip ensemble et dans l'ordre (message affiche), soudees au reordonnancement. N = nombre de posts coches. Memes dates (debut + k x X h), meme apercu, memes refus, meme creation tout ou rien. Couvert par tests/test_publish.py et tests/test_web.py, dans le scope deja ouvert de TASK-5bbf77badfd0 (pas d'amend de perimetre necessaire).
