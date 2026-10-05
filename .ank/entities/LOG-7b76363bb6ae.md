---
id: LOG-7b76363bb6ae
type: log
title: QA zone webcam, MESURE (lecture seule, 12 clips reels stream_split des 2 VOD, 10 paires d'images
created: 2026-10-05T22:16:50Z
author: w-57453bb1e834
scope:
  - clipper/reframe.py
  - clipper/qa.py
  - clipper/llm/__init__.py
  - tests/test_reframe.py
  - tests/test_qa.py
  - tests/test_llm.py
  - config.example.toml
  - clipper/assets/config.example.toml
about: TASK-57453bb1e834
seq: 4
schema: 4
version: 1
---

 par clip dans le clip rendu, script research/facecam-5745/measure_qa.py). Regle du critere 'visage OU mouvement' (mouvement = >= 0,1 % des pixels different de >= 8 niveaux entre 2 images a 0,5 s) : part = 1,0 sur les 11 bons cadrages ET sur le seul vrai mauvais cadrage (v2888230655/01, debut 855 s en Just Chatting, rectangle 1404,408 pose sur la salle/le chat), car le mouvement vaut 1,0 partout (chat qui defile, jeu, bruit video). Sur la zone jeu des memes clips (mauvais cadrage simule) mouvement 0,4 a 1,0 : la regle ne separe pas. Visage seul : bons 1,0 (x11), mauvais reel 0,3, zone jeu 0,1 a 0,8 -> separe sur ce petit echantillon (un seul vrai mauvais clip, les autres sont simules) mais ce n'est pas la regle du critere et un seul vrai mauvais exemple ne suffit pas a fixer un seuil. DECISION : pas de controle de la zone webcam dans qa (aucun code, pas de reglage) ; piste : controle 'visage seul' en avertissement quand plus de vrais mauvais clips existeront (le nouveau choix par periode doit d'abord les eviter).
