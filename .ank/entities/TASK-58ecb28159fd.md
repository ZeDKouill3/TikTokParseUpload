---
id: TASK-58ecb28159fd
type: task
slug: download-viter-le-1080p-premium-m3u8-fichier-4-5
title: "download : éviter le 1080p « premium » m3u8 (fichier 4 à 5 fois plus gros)"
created: 2026-09-25T16:47:53Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/download.py
  - tests/test_download.py
blocked_by: []
done_criteria: |
  Le sélecteur de format de clipper.download préfère, jusqu'à 1080p, une vidéo H.264 (vcodec avc1) en téléchargement https direct (pas m3u8) avec l'audio m4a, et ne retombe sur les autres formats qu'en l'absence de celle-ci ; le plafond 1080p et la sortie mp4 restent inchangés ; un test sans réseau vérifie le choix sur une liste de formats enregistrée contenant un 616 premium m3u8 vp9 et un 137 avc1 https ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Constat essai réel 2026-09-25 (sZi-qJ-5ptA, 1 h 52) : le sélecteur actuel a pris le format 616 (1080p premium, m3u8, vp9), soit environ 4 à 5 Go, alors qu'un 1080p standard en ferait environ 1. H.264 est aussi plus simple à décoder pour scenes/reframe et pour NVENC côté render.
