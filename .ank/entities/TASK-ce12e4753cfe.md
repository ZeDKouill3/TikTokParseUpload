---
id: TASK-ce12e4753cfe
type: task
slug: scenes-acc-l-rer-l-tape-34-min-pour-7-h-de-vod-e
title: "Scenes : accélérer l'étape (34 min pour 7 h de VOD) en gardant les mêmes coupes, mesuré sur une vraie VOD"
created: 2026-10-09T11:23:04Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Constat réel 09/10 : l'étape scenes a pris 34 min (workspace/v2894981843/pipeline.json, 09:46:49 -> 10:20:24 UTC) pour une VOD de 7 h 10 en 1080p, la plus longue étape restée sur CPU (transcription GPU : 5 min). Historique : TASK-03e7 (scenes -17 %), TASK-908e fermée ; décodage NVDEC mesuré PLUS LENT que le CPU le 08/10 (ne pas le retenter). clipper/scenes.py analyse déjà en basse résolution avec analysis_max_fps (CONFIG_DEFAULTS ~l.56-63, filtre ffmpeg ~l.249) et des segments en parallèle. (1) Mesurer d'abord où part le temps (décodage ffmpeg vs détecteur PySceneDetect vs attente) sur un extrait réel de 20 min de workspace/v2894981843/v2894981843.mp4 (copie dans un dossier temporaire, PC sans autre calcul lourd), et écrire les mesures dans le log de la tâche (ank log). (2) Essayer les leviers CPU, chacun mesuré seul : nombre de segments parallèles / threads ffmpeg ; -skip_frame / -skip_loop_filter / décodage à résolution réduite (lowres) si le codec le permet ; analysis_max_fps plus bas (15, 10). Retenir le meilleur compromis : gain de temps >= 25 % sur l'extrait ET au moins 95 % des coupes de scènes de référence (version actuelle sur le même extrait) retrouvées à 0,5 s près, et pas plus de 5 % de coupes en plus. Si aucun levier ne tient ces deux conditions, ne rien changer au code, écrire pourquoi dans le log et terminer par released avec la raison. (3) Les nouveaux réglages éventuels vivent dans CONFIG_DEFAULTS de scenes.py ; aucun changement de format de scenes.json ; ADR-4e57 / SPEC-b0f3 R4bis respectés (scenes ne lit la config d'aucune autre étape). (4) Tests unitaires CPU sans réseau dans tests/test_scenes.py pour toute nouvelle option (construction de la commande ffmpeg, validation des réglages) ; le benchmark réel n'est PAS un test par défaut (script jetable hors dépôt ou test optionnel sauté par défaut). CHANGELOG [Non publié] Modifié avec le gain mesuré.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 3
---
