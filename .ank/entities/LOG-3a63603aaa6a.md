---
id: LOG-3a63603aaa6a
type: log
title: "Controle reel termine avec succes : 4 clips (00,01,02,05) de workspace/v2887271276 rendus en"
created: 2026-09-30T15:23:32Z
author: w-b44e504d655b
scope:
  - clipper/reframe.py
  - clipper/render.py
  - clipper/subtitles.py
  - clipper/pipeline.py
  - clipper/assets
  - tests/test_reframe.py
  - tests/test_render.py
  - tests/test_subtitles.py
  - docs/GUIDE.md
  - config.example.toml
about: TASK-b44e504d655b
seq: 7
schema: 4
version: 1
---

 agencement split via le preset local research/presets/madajel.toml mis a jour (stream_variant=split, badge_enabled, title_enabled=false, cta_enabled=false), sorties dans research/madajel/split/ (copie de travail : workspace/video hardlinke, jamais workspace/ ni output/ du depot touches). Captures milieu de clip comparees visuellement a research/madajel/agencement/rendu-5400.png : agencement (webcam haut avec marges noires, jeu bas pleine largeur), badge (logo Twitch + 'madajel' sur fond noir a la jonction) et style des sous-titres (blanc, mot en cours en violet Twitch #9146FF, contour noir, pas d'ombre) conformes a la maquette. Deuxieme bug trouve et corrige par ce meme controle : le calque de surbrillance par mot est un champ Text ASS separe par mot (Dialogue independant), dont un espace de tete est rogne par libass (contrairement a la ligne de base, un seul champ Text continu) -- corrige en avancant le curseur de la largeur de l'espace sans le dessiner.
