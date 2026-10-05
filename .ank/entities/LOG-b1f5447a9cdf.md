---
id: LOG-b1f5447a9cdf
type: log
title: "Correctif : scroll_script = pas de 80 % du conteneur interne (rend true au bas), list_posts cumule"
created: 2026-10-05T19:00:24Z
author: w-b66a4a8745cd
scope:
  - clipper/tiktok.py
  - clipper/assets/tiktok_selectors.toml
  - tests/test_tiktok.py
about: TASK-b66a4a8745cd
seq: 3
schema: 4
version: 1
---

 les lignes par id a chaque pas, fin = bas atteint + 2 pas sans nouvelle ligne ; stats_scroll_rounds 10 -> 100. Pas de total affiche sur la page (rien a respecter, rien invente). Tests rouges sans correctif (7 echecs) puis 239 verts. Releve de controle reel (list_posts sur la vraie page, lecture seule) : 42 posts lus, de 7 oct. 09:00 au plus ancien 3 oct. 18:47 (8 avant).
