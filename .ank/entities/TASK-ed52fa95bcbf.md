---
id: TASK-ed52fa95bcbf
type: task
slug: recadrage-stream-webcam-localis-e-par-clip-sur-u
title: "Recadrage stream : webcam localisée PAR CLIP sur un échantillon d'images (vote), position fixée du style prioritaire, aperçu du rectangle retenu"
created: 2026-10-05T21:36:55Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
  - clipper/web/app.py
  - clipper/web/static/screens/clips.js
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Tests verts, sans réseau ni vrai modèle (détecteur de visages simulé) : constats réels 2026-10-05 : (a) v2888230655 (Hctuan) : la webcam change de place pendant la VOD (plein écran « Just Chatting » au début, petite webcam en bas à gauche pendant le jeu) mais facecam.json donne une seule position pour toute la vidéo (x=1404, y=408) ; (b) v2887364910 (TheGuill84, casque, petite webcam à gauche) : visage reconnu sur 7 % des images clés seulement, sous le seuil de 10 % -> tous les clips en letterbox. Attendu : (1) pour chaque clip, la webcam est localisée sur un échantillon de N images réparties sur la durée du clip (réglage CONFIG_DEFAULTS, ex. 10), par vote : une position retenue si au moins une part réglable des images où un visage est trouvé concordent (tolérance existante) ; (2) si le clip ne tranche pas, la position de la vidéo entière (facecam.json actuel) sert d'indice si elle est présente dans les images du clip ; sinon le clip est rendu en letterbox (règle actuelle), décision et raison écrites par clip ; (3) un style peut fixer la position source de la webcam ([reframe] facecam_rect = {x,y,w,h} en pixels source) : elle prime, aucune détection ; (4) une image d'aperçu par clip (image du clip avec le rectangle retenu, ou « letterbox : raison ») est écrite sous workspace/<id>/reframe/ et affichée dans l'écran Clips ; (5) tests : clip dont la webcam change de place par rapport à la vidéo, clip sans webcam -> letterbox, style à position fixée, vote avec images ratées.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Choix utilisateur 2026-10-05 : « d'accord pour la 2, sur un échantillon de plusieurs images dans la vidéo ». Écart avec SPEC-8257 et SPEC-76dc (proposées, non ratifiées) qui disent « localisation une fois par vidéo » : ajouter une spec successeur (ank new spec --supersedes SPEC-76dc...) décrivant la localisation par clip, à laisser proposée pour ratification humaine (ne jamais ank accept).
