---
id: TASK-53e3d4cee2f9
type: task
slug: reframe-la-vraie-webcam-choisie-par-claude-est-r
title: "Reframe : la vraie webcam choisie par Claude est rejetée au contrôle par clip (TheGuill v2887364910, 6/6 clips en letterbox)"
created: 2026-10-05T23:38:16Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
blocked_by: [TASK-baa8d32f7076]
done_criteria: |
  Défaut constaté 2026-10-06 : v2887364910 (TheGuill84, petite webcam encadrée en haut à gauche, casque) période 1 : Claude choisit le bon rectangle (workspace/v2887364910/facecam.json, planche facecam/period_1.jpg), mais _clip_facecam (contrôle par clip : noir / bords / figée, facecam_clip_min_share = 0.8) rejette la webcam sur TOUS les clips (1/10 à 9/16 images clés vivantes) -> 6 clips en letterbox (workspace/v2887364910/reframe/*.json layout_reason). Méthode ank-diagnose : mesurer en LECTURE SEULE sur les images clés réelles de cette vidéo (workspace/v2887364910, jamais écrire dans workspace/ ni output/ ; copies sous research/ si besoin) laquelle des règles (noir, bords _rect_edges_found, figée _rect_is_frozen) fait tomber chaque image, résultats chiffrés dans ank log ; vérifier aussi v2888230655 (Hctuan, contrôle correct aujourd'hui) pour ne pas le casser. Corriger la cause (pas en baissant facecam_clip_min_share au hasard) ; la règle d'origine (SPEC-8257/76dc : webcam noire, absente ou figée -> letterbox) reste vraie pour une webcam réellement coupée. Test de non-régression reproduisant le cas (images synthétiques ou crops réduits copiés en fixture légère < 200 Ko), rouge avant le correctif. Aucun réseau, aucun vrai Claude.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/b281fc55d711@c1d232e
    tree: scope/97dda33c6222
    criteria: 0eac961a4027
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
