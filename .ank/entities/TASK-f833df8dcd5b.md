---
id: TASK-f833df8dcd5b
type: task
slug: format-stream-d-cider-par-clip-selon-la-pr-sence
title: "Format stream : décider par clip selon la présence du rectangle de webcam statique, pas selon la détection de visage"
created: 2026-09-30T11:07:57Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
blocked_by: []
done_criteria: |
  Une facecam statique déjà localisée (facecam.json) est gardée pour un clip tant que le rectangle est présent et vivant dans le clip (contenu non noir/non figé, bords de l'incrustation retrouvés sur les images clés du clip), même si mediapipe ne détecte pas le visage (webcam petite, jeu sombre, casque, tête tournée) ; la détection de visage reste un indice pour LOCALISER la facecam, plus une condition par clip ; seuils séparés et réglables dans CONFIG_DEFAULTS (localisation vs présence par clip) ; un clip où la webcam est absente/noire/masquée (écran de pause, BRB) reste letterbox avec raison explicite journalisée (ADR-ad2e) ; tests unitaires sur images synthétiques (rectangle statique avec visage non détecté -> stream ; rectangle noir -> letterbox) ; contrôle réel sur workspace/v2887271276 (reframe seulement, sans LLM) : les clips passent en stream, captures PNG dans research/madajel/ ; SPEC-3a88 (format stream) relue : si la règle 'visage sur X % des images clés du clip' y est écrite, ank release avec la citation au lieu de coder.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Remarque utilisateur 2026-09-30 : « la caméra est statique pourtant ». VOD Twitch v2887271276 (Madajel, Silent Hill, webcam 354x252 à gauche, jeu très sombre, casque) : avec facecam_min_share 0.1, facecam localisée {'x': 0, 'y': 346, 'w': 354, 'h': 252} (visage sur 14 % des images clés), mais chaque clip retombe en letterbox : « visage dans la facecam sur 0% des images clés du clip ». Le même réglage facecam_min_share sert aux deux décisions (reframe.py ~l.1446 et ~l.1509). En letterbox, la webcam est coupée et une bande reste au bord gauche : moche.
