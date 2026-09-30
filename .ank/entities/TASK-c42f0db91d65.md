---
id: TASK-c42f0db91d65
type: task
slug: spec-agencement-stream-split-r-glable-webcam-hau
title: "Spec : agencement stream 'split' réglable (webcam haut / jeu bas), badge de chaîne, style des sous-titres — successeur de SPEC-8257"
created: 2026-09-30T14:16:45Z
author: nicoc@zedk_ordi
status: done
scope:
  - AGENTS.md
blocked_by: []
done_criteria: |
  Nouvelle spec (ank new spec --supersedes SPEC-8257564db9db, proposée, jamais ank accept) : reprend SPEC-8257 à l'identique pour la localisation et la présence de la webcam ; ajoute un agencement stream 'split' dont TOUTES les cotes sont réglables (CONFIG_DEFAULTS) avec pour valeurs de référence celles de research/madajel/agencement/madajel-tiktok.json (webcam dest 20,0,1040x640 avec source recadrée au ratio de la destination, centrée sur le rectangle détecté ; gameplay dest 0,640,1080x1280, source recadrée au ratio de la destination, centrée horizontalement, excluant la webcam d'origine quand c'est possible) ; règle de ratio : jamais de déformation (source recadrée au ratio de destination) ; badge de chaîne optionnel (logo PNG fourni par config + nom, fond noir, carré de logo à taille fixe et glyphe réduit d'un facteur réglable, position réglable, par défaut à cheval sur la jonction webcam/jeu), qui remplace le pseudo texte quand il est activé ; style des sous-titres réglable (police, taille, majuscules, couleur, couleur du mot courant, contour, ombre, position) avec le style de référence : Poppins ExtraBold, majuscules, blanc, mot courant #9146FF, contour noir épais, sans fond ; titre d'écran et carte de fin désactivables par config (désactivés dans ce modèle) ; le format stream actuel reste le défaut global (le 'split' est choisi par config) ; zone sûre TikTok : textes dans x150-930/y160-1520 ; rendus de référence cités (research/madajel/agencement/rendu-5400.png, rendu-2400.png) ; AGENTS.md cite la nouvelle spec comme proposée. Aucun code. Ne jamais citer le nom de la chaîne réelle dans la spec (dire 'une streameuse Twitch') : dépôt public.
criteria_by: creator
proof:
  - type: assertion
    ref: SPEC-76dc6a1cbccb
    criteria: 174b279776ac
    via: submitted
schema: 4
version: 3
---

Décision utilisateur 2026-09-30 : pour une streameuse Twitch, reproduire le style de ses propres TikTok (research/madajel/tiktok/montage.png) : webcam en haut ~1/3, jeu en bas ~2/3 remplissant la largeur, badge Twitch (logo violet + nom sur fond noir) à la jonction, sous-titres gras majuscules blanc/violet contour noir, pas de titre d'écran, pas de carte de fin. L'utilisateur a placé les blocs dans l'éditeur research/madajel/editeur/editeur.html ; JSON nettoyé par l'orchestrateur : research/madajel/agencement/madajel-tiktok.json ; rendus ffmpeg validés : research/madajel/agencement/rendu-5400.png et rendu-2400.png. Lire SPEC-8257564db9db, SPEC-6a867ae54f94 (contrat de sortie, titres sobres, CTA) et ADR-ad2e. Preuve : --proof assertion:<id de la spec>.
