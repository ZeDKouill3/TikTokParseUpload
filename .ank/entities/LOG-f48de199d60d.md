---
id: LOG-f48de199d60d
type: log
title: "APRES (meme charge : CPU 83-96 %, 3 pipelines en parallele). scenes decode via ffmpeg en"
created: 2026-09-29T00:48:56Z
author: w-1f16
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
about: TASK-1f16c927324f
seq: 3
schema: 4
version: 1
---

 sous-processus (decodeur choisi par ffmpeg pour l'AV1 = libdav1d, -c:v force possible via CONFIG_DEFAULTS.decoder), analyse en 256 px de large et au plus 30 img/s (analysis_width, analysis_max_fps), keyframes extraites par ffmpeg -ss en pleine resolution (1920x1080 verifie). Extrait 1 (-ss 600 -t 60 -c copy, 3600 images, 1 coupe) : detection 79,5 s (45 img/s) -> 4,3 s (832 img source/s) = x18 ; etape entiere (detection + 13 keyframes) 102,5 s -> 8,2 s / 8,3 s = x12,5. Coupe 40,550 -> 40,567 s (ecart 0,017 s). Extrait 2 choisi pour sa densite de coupes (-ss 2620 -t 60 -c copy) : etape 105,3 s -> 10,5 s = x10,0 ; 8 coupes avant [7.833, 10.833, 12.867, 13.817, 25.017, 25.65, 56.783, 57.767] / apres [7.833, 10.833, 12.867, 13.833, 25.033, 25.667, 56.8, 57.767] : ecart max 0,017 s, moyen 0,008 s ; 18 keyframes des deux cotes. A 60 img/s d'analyse la detection prend 7,1 s au lieu de 4,3 s pour les memes coupes a 0,0 s : le plafond 30 img/s est garde. Le seek OpenCV coutait ~1,7 s par keyframe (libaom redecode le GOP) : l'extraction passe aussi par ffmpeg.
