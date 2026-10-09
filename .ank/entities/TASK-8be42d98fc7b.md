---
id: TASK-8be42d98fc7b
type: task
slug: scenes-m-me-test-en-480p-vitesse-et-coupes-vs-10
title: "Scenes : même test en 480p (vitesse et coupes vs 1080p), implémenter seulement si la mesure le justifie"
created: 2026-10-09T12:11:08Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/download.py
  - clipper/scenes.py
  - clipper/workspace.py
  - tests/test_download.py
  - tests/test_scenes.py
  - tests/test_workspace.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Suite de TASK-1bf7471e2532 (fermée : proxy 360p obtenu par réencodage, scenes 89 % plus rapide mais 58/69 coupes retrouvées = 84 % et 25 % de coupes en trop ; mesures dans ses logs) et TASK-ce12e4753cfe (scenes limitée par le décodage 1080p60). Demande de l'utilisateur : refaire le test avec une version 480p. (1) MESURE D'ABORD, même protocole que TASK-1bf7 : même extrait de 20 min (t=3600-4800 s) de la vraie VOD v2894981843 (workspace/v2894981843/v2894981843.mp4, copie dans un dossier temporaire hors workspace) ; essayer d'abord de télécharger la vraie version 480p de Twitch (https://www.twitch.tv/videos/2894981843, yt-dlp, format ~480p) ; si le réseau Twitch refuse (usher.ttvnw.net réinitialise), produire la 480p par réencodage ffmpeg (H.264, 30 i/s, débit proche d'une 480p Twitch ~1,5 Mb/s) et le dire. Comparer scenes sur la 1080p (référence) et sur la 480p : temps, coupes de référence retrouvées à 0,5 s près, coupes en trop ; essayer aussi analysis_width plus grand (par ex. 320 ou 480) sur la 480p si cela rapproche les coupes. Écrire toutes les mesures dans le log de la tâche (ank log). (2) Critère pour implémenter : >= 25 % plus rapide au total (téléchargement de la 480p compris si réel) ET >= 95 % des coupes retrouvées ET <= 5 % de coupes en trop. Sinon : code inchangé, mesures dans le log, terminer par released avec la raison et le tableau des mesures. (3) Si le critère tient : même implémentation que décrite dans TASK-1bf7471e2532 critère (3) avec [download] analysis_proxy_height défaut 480 (fichier <video_id>.analysis.mp4, scenes l'utilise si sa durée correspond, sinon la source avec journal ; ADR-b16b ; échec du téléchargement d'analyse = warning, pas d'arrêt). (4) Tests CPU sans réseau pour tout code ajouté (tests/test_download.py, tests/test_scenes.py, tests/test_workspace.py). CHANGELOG [Non publié] Modifié avec le gain mesuré si implémenté.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
