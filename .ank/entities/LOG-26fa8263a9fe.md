---
id: LOG-26fa8263a9fe
type: log
title: Lecture spec/ADR faite. Choix d'implementation pour lever l'ambiguite de placement du pseudo ('sous
created: 2026-09-30T09:42:27Z
author: w-0b18d9d6bd0c
scope:
  - clipper/render.py
  - clipper/captions.py
  - clipper/subtitles.py
  - clipper/qa.py
  - tests/test_render.py
  - tests/test_captions.py
  - tests/test_subtitles.py
  - tests/test_qa.py
  - docs/GUIDE.md
  - AGENTS.md
about: TASK-0b18d9d6bd0c
seq: 2
schema: 4
version: 1
---

 le titre, dans la bande floue du haut') : le titre est ancre en bas de sa zone (title_lift px du bord) ; il n'y a donc de la place SOUS l'encadre du titre que si on l'y reserve explicitement. Quand cta_enabled+cta_handle, je calcule la taille/hauteur du pseudo (mesure avec la vraie police, palier par palier) puis j'appelle layout_title avec un title_lift effectif = title_lift + cta_handle_gap + hauteur_pseudo : le titre remonte, le pseudo se place dans l'espace ainsi libere, juste au-dessus du buffer title_lift d'origine. Sans cta (defaut), title_lift est inchange -> rendu letterbox/stream identique a l'existant (verifie par les tests actuels non modifies). La carte de fin ('Abonne-toi !') est un encadre blanc/texte noir, meme style que le titre mais centre (pas ancre en bas) dans text_zones.subtitles, affiche par un overlay ffmpeg avec enable=gte(t,duration-cta_seconds). Les sous-titres pendant ces secondes sont retires en tronquant une COPIE du .ass (jamais l'original ecrit par l'etape subtitles - ADR-b16b, aucun import de subtitles.py) : les evenements dont la fin depasse le cutoff sont raccourcis a ce cutoff, ceux qui commencent apres sont supprimes. Ceci evite de toucher clipper/subtitles.py et clipper/qa.py, hors du strict necessaire (scope de la tache autorise mais n'oblige pas a les toucher).
