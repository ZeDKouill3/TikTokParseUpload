---
id: LOG-6c46af7dc9a5
type: log
title: mesure sur WVjOSRFWm4c (2326 images cles, vrai detecteur mediapipe, 255s) avec mon 1er correctif
created: 2026-09-29T15:18:19Z
author: w-65192877dbe0
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
about: TASK-65192877dbe0
seq: 3
schema: 4
version: 1
---

 applique : edge_reason toujours 'bord(s) droit ... introuvable(s)' -> rect inchange {x:1534,y:131,w:200,h:142}. Cause : face=[1598.5,166.5,1668.8,237.5] fw=70.3px -> search_x=round(70.3*3.0)=211, gap_x=4, limit_droit=min(1919, 1668.8+4+211)=1884 < 1919 : le budget de recherche (facecam_edge_search_ratio) n'atteint meme pas le vrai bord (distance reelle 251px), donc mon 1er correctif (retour du bord seulement si limit==border) ne se declenche jamais ici -- HYPOTHESE REFUTEE : corriger _edge_position pour renvoyer le bord seul ne suffit pas, gauche/haut/bas sont trouves normalement (seul droit manque).
