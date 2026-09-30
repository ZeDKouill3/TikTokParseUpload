---
id: LOG-7f99b225d4ff
type: log
title: Rendu final ffmpeg (pas de code de production) a partir de
created: 2026-09-30T14:08:34Z
author: w-28cdfd9b22a4
scope:
  - AGENTS.md
about: TASK-28cdfd9b22a4
seq: 7
schema: 4
version: 1
---

 research/madajel/agencement/madajel-tiktok.json (cotes nettoyees par l'orchestrateur, webcam source recadree 354x218 y=363, sous-titres y=710) : research/madajel/agencement/rendu-5400.png et rendu-2400.png, 1080x1920, sur frame_5400.jpg et frame_2400.jpg (research/madajel/editeur/). Pas de carte de fin (confirme par l'utilisateur en cours de tache : endcard.visible=false, non rendue). Pipeline : fond = source scale increase + crop centre 1080x1920 + gblur sigma=20 + assombri (eq brightness=-0.08) ; webcam crop(354x218 @0,363) scale 1040x640 overlay (20,0) ; gameplay crop(912x1080 @504,0) scale 1080x1280 overlay (0,640) ; badge et sous-titres pre-composes en PNG transparents (ImageMagick, texte/logo uniquement, pas de logique clipper) puis overlay ffmpeg. Badge (420x100, overlay 330,590) : carre violet #9658FF (echantillonne) + twitch-logo.png reel redimensionne a 65% (58x65 dans 100x100, resize contain + centre) + 'Madajel' Poppins ExtraBold 40px blanc sur noir. Sous-titres (overlay centre dans 780x150 @150,710, donc a x=296 y=726 pour l'image 488x118) : 'MOI,' blanc + 'J'VOIS' violet #9146FF (couleur demandee explicitement pour le surlignage, differente du violet du logo), Poppins ExtraBold 80px, contour noir epais (strokewidth 6), PAS de fond noir (texte directement sur le fond flou/gameplay, transparent). Piege ImageMagick rencontre et corrige : composer une image blanc+noir seule (ex. 'MOI,' avant d'ajouter le mot violet) puis la reecrire sur disque et la relire fait basculer son stockage PNG en Grayscale (aucune couleur ne le justifiait a cet instant) ; tout compositing ulterieur avec une couleur (violet) sur cette base rechargee perd la teinte. Fix : ne jamais faire de va-et-vient disque au milieu d'une composition multicolore, tout faire en un seul appel magick (canvas transparent en memoire, composites successifs, sauvegarde unique avec -define png:color-type=6). Verifie par Read tool sur les deux PNG finaux : webcam/jeu/badge/sous-titres bien places, aucune bavure, contenu webcam en bord de crop (trophee visible cote droit) confirme correct par comparaison avec le crop webcam seul (correspond exactement au rectangle source demande, pas un bug de compositing).
