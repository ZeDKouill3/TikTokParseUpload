---
id: TASK-28cdfd9b22a4
type: task
slug: spec-maquette-nouvel-agencement-stream-gameplay
title: "Spec + maquette : nouvel agencement stream (gameplay principal au centre, webcam plus petite au-dessus, sous-titres sous le jeu, pseudo petit dans un coin du jeu)"
created: 2026-09-30T13:09:33Z
author: nicoc@zedk_ordi
status: closed
scope:
  - AGENTS.md
blocked_by: []
done_criteria: |
  1) Maquettes PNG 1080x1920 construites avec ffmpeg (sans toucher au code) sur de vraies images de workspace/v2887271276/v2887271276.mp4 (webcam source x0 y346 w354 h252), dans research/madajel/maquettes/ : au moins 2 variantes (A : gameplay pleine largeur 16:9 sans recadrage ; B : gameplay zoomé plus haut, léger recadrage des côtés), chacune avec titre sobre en haut, webcam plus petite centrée au-dessus du jeu, gameplay au centre de l'écran, sous-titres sous le jeu, pseudo twitch.tv/... en petit dans un coin bas du gameplay, plus une image de la carte de fin « Abonne-toi ! » ; zone sûre TikTok respectée (aucun texte au-dessus de y=160 ni en dessous de y=1520, ni hors x 150-930 sauf le pseudo si la spec le justifie) ; cotes (px) de chaque zone écrites dans ank log. 2) Nouvelle spec (ank new spec --supersedes SPEC-8257564db9db, proposée, jamais ank accept) : reprend SPEC-8257 (détection/présence de la webcam inchangées) avec le nouvel agencement stream en cotes réglables (CONFIG_DEFAULTS) et la position du pseudo en format stream (coin bas du gameplay, taille réduite) ; indique explicitement ce qu'elle change par rapport à SPEC-6a867ae54f94 pour le format stream (le pseudo n'y est plus sous le titre) ; si ank exige une 2e supersession pour cela, le signaler dans ank log au lieu de la créer. AGENTS.md : nouvelle spec citée comme proposée. Aucun code de production.
criteria_by: creator
schema: 4
version: 4
---

Retour utilisateur 2026-09-30 sur les clips de démo stream (research/madajel/demo-clips-v2) : « caméra trop grosse, gameplay en principal, bien au centre ; la caméra doit être au-dessus du gameplay, la vidéo au centre, en principal de l'écran ; ensuite le sous-titre en dessous du jeu, avec le twitch en plus petit en bas dans un coin de la vidéo. On est sur la bonne voie, juste des agencements. » Agencement actuel (SPEC-8257) : webcam agrandie en haut (~40 % de la hauteur), jeu dessous, sous-titres entre les deux ; pseudo sous le titre (SPEC-6a86). Proposition orchestrateur (à affiner sur maquette) : titre ~y160-330 ; webcam ~500x360 centrée ~y360-720 ; gameplay 1080x608 ~y740-1348 ; sous-titres ~y1370-1520 ; pseudo ~28 px dans le coin bas droit du gameplay ; carte de fin dans la zone des sous-titres. L'utilisateur choisira sur les maquettes avant ratification. Preuve : --proof assertion:<id de la spec>.
