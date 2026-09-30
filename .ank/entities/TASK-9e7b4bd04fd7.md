---
id: TASK-9e7b4bd04fd7
type: task
slug: spec-successeur-de-spec-3a88-format-stream-pr-se
title: "Spec : successeur de SPEC-3a88 (format stream) — présence du rectangle de webcam statique au lieu du visage par clip"
created: 2026-09-30T11:30:09Z
author: nicoc@zedk_ordi
status: open
scope:
  - AGENTS.md
blocked_by: []
done_criteria: |
  Nouvelle spec créée par ank new spec --supersedes SPEC-3a88 (proposée, jamais ank accept), reprenant SPEC-3a88 à l'identique sauf : règle 1 (localisation) : le visage reste un indice pour trouver le rectangle, avec seuil de localisation séparé (défaut plus bas que 0,8, réglable) et/ou détection des bords d'une incrustation statique ; règle 2 (choix par clip) : un clip est en stream si le rectangle de webcam est présent et vivant dans le clip (contenu non noir, non figé, bords de l'incrustation retrouvés) sur au moins une part réglable de ses images clés, SANS exiger la détection du visage ; clip letterbox si la webcam est absente/noire/masquée (pause, BRB), raison journalisée (ADR-ad2e) ; règle 3 inchangée ; cas motivant cité (VOD Twitch, webcam 354x252, jeu sombre, visage détecté sur 14 % des images clés globales et 0 % par clip alors que la webcam est visible) ; AGENTS.md cite la nouvelle spec comme proposée. Aucun code.
criteria_by: creator
schema: 4
version: 1
---

Remarque utilisateur 2026-09-30 : « la caméra est statique pourtant ». TASK-f833df8dcd5b (implémentation) a été relâchée parce que SPEC-3a88 règle 2 impose « visage présent dans le rectangle sur au moins facecam_min_share des images clés du clip ». Démo réelle v2887271276 : facecam trouvée {'x': 0, 'y': 346, 'w': 354, 'h': 252} avec facecam_min_share 0.1, puis 0 % par clip -> letterbox avec une bande de webcam coupée au bord ; forcé à 0.0 dans un preset local, les 4 clips en stream sont bons (research/madajel/demo-clips-stream). Lire SPEC-3a88 en entier et SPEC-6a476ca57f39. Preuve : --proof assertion:<id de la spec>.
