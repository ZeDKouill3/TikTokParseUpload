---
id: TASK-ad9a7e8b414b
type: task
slug: scenes-m-me-test-en-720p-vitesse-et-coupes-vs-10
title: "Scenes : même test en 720p (vitesse et coupes vs 1080p), implémenter seulement si la mesure le justifie"
created: 2026-10-09T21:24:16Z
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
  Suite de TASK-1bf7471e2532 (360p réencodée : 89 % plus rapide, 84 % des coupes, 25 % en trop) et TASK-8be42d98fc7b (vraie 480p Twitch : 82 % plus rapide, 87 % des coupes, 18 % en trop ; analysis_width 480 : 93 % / 23 %), mesures dans leurs logs (ank log). Demande de l'utilisateur : refaire le test en 720p. (1) MESURE D'ABORD, même protocole : extrait de 20 min (t=3600-4800 s) de la vraie VOD v2895010701 (workspace/v2895010701/v2895010701.mp4, 1080p60 ; l'ancienne v2894981843 a été purgée), copie de l'extrait dans un dossier temporaire sous research/ (jamais dans workspace/). Télécharger la vraie 720p de Twitch (https://www.twitch.tv/videos/2895010701, yt-dlp, format 720p30 ou 720p60, --download-sections 3600-4800) ; si Twitch refuse, réencoder en 720p avec ffmpeg (H.264, débit proche d'une 720p Twitch) et le dire. Comparer scenes sur la 1080p (référence) et la 720p : temps (téléchargement de la 720p compris), coupes de référence retrouvées à 0,5 s près, coupes en trop ; essayer aussi analysis_width plus grand sur la 720p si cela rapproche les coupes. Toutes les mesures dans ank log. (2) Critère pour implémenter : >= 25 % plus rapide au total ET >= 95 % des coupes retrouvées ET <= 5 % de coupes en trop. Sinon : code inchangé, tableau des mesures dans le log, terminer par released avec la raison. (3) Si le critère tient : implémentation décrite dans TASK-1bf7471e2532 critère (3) avec [download] analysis_proxy_height défaut 720 (fichier <video_id>.analysis.mp4, scenes l'utilise si sa durée correspond, sinon la source avec journal ; ADR-b16b ; échec du téléchargement d'analyse = warning, pas d'arrêt). (4) Tests CPU sans réseau pour tout code ajouté. CHANGELOG [Non publié] Modifié avec le gain mesuré si implémenté.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
