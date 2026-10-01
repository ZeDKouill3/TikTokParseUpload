---
id: TASK-dc9de7d5b660
type: task
slug: console-v2-corrections-apr-s-le-premier-tour-min
title: "console v2 : corrections après le premier tour (miniatures des clips, nouvelle chaîne, ANSI, VRAM, durées d'étapes)"
created: 2026-10-01T10:26:40Z
author: nicoc@zedk_ordi
status: in_progress
scope:
  - clipper/web/app.py
  - clipper/web/static/**
  - clipper/pipeline.py
  - clipper/render.py
  - clipper/gpu.py
  - tests/test_web.py
  - tests/test_pipeline.py
  - tests/test_render.py
  - tests/test_gpu.py
blocked_by: []
done_criteria: |
  Tests ciblés, aucun réseau ni GPU, prouvent : (1) miniatures : une fonction pipeline.clip_thumbnail(config, video_id, clip_id) (même schéma que pipeline.preview_subtitles, le web ne traite jamais de vidéo, ADR-09ad) produit et met en cache une image JPEG de largeur <= 360 px de output/<video_id>/<clip_id>.mp4 (ffmpeg via render, une seule extraction, réutilisée tant que le mp4 n'a pas changé de mtime) ; une route GET la sert ; la galerie Clips affiche <img loading="lazy"> vers cette route et AUCUNE balise <video> dans la grille (la vidéo n'est chargée qu'à l'ouverture d'un clip), et pagine par 24 clips (bouton « Afficher plus ») ; test statique sur clips.js + test de la route avec ffmpeg simulé ; (2) le bouton « Nouvelle chaîne » ouvre réellement la fenêtre de création (test : la fonction de panneau appelée existe et la classe CSS du panneau modal est définie et visible ; corriger la cause réelle) ; (3) tout message d'erreur affiché par l'API (raison d'échec, journal) est débarrassé des séquences ANSI (\x1b[...m) côté serveur, testé ; (4) le panneau Matériel n'importe plus torch : la VRAM passe par clipper.gpu (ADR-fb9b), ou est annoncée indisponible avec la raison, sans erreur « No module named » ; (5) une étape sautée parce que déjà faite ne réécrit plus started_at/finished_at : la fiche vidéo garde la vraie durée de la première exécution (test sur pipeline.json) ; (6) tests existants verts. python -m pytest -q tests/test_web.py tests/test_pipeline.py tests/test_render.py tests/test_gpu.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

Premier tour de la console v2 avec l'utilisateur (2026-10-01) : la galerie Clips fait ramer le navigateur (105 balises video préchargées) ; le bouton Nouvelle chaîne n'ouvre rien ; les erreurs yt-dlp s'affichent avec leurs codes couleur ANSI ; le panneau Matériel lit la VRAM via torch (non installé) ; la fiche vidéo affiche 0 s pour les étapes déjà faites.
