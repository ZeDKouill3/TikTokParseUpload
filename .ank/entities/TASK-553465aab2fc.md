---
id: TASK-553465aab2fc
type: task
slug: spec-successeur-de-spec-6127-avec-appel-l-abonne
title: "Spec : successeur de SPEC-6127 avec appel à l'abonnement optionnel (pseudo permanent + carte de fin), désactivé par défaut"
created: 2026-09-30T08:58:21Z
author: nicoc@zedk_ordi
status: open
scope:
  - AGENTS.md
blocked_by: []
done_criteria: |
  Une nouvelle spec créée par ank new spec --supersedes SPEC-6127 (statut proposé, jamais ank accept) reprend SPEC-6127 à l'identique et ajoute : (1) option de config (désactivée par défaut, donc rendu par défaut inchangé) : pseudo de chaîne discret (ex. twitch.tv/<handle>) sous le titre d'écran pendant tout le clip, dans la bande floue du haut ; (2) carte de fin « Abonne-toi ! » (texte réglable) sur les N dernières secondes (défaut 2 s) dans la bande floue du bas, qui remplace les sous-titres pendant ces secondes ; (3) mêmes règles de mesure/zone sûre/erreur explicite que les autres textes (jamais débordant ni tronqué) ; (4) formats concernés (letterbox et stream/facecam_gameplay au moins) ; (5) le sidecar indique si le CTA est présent ; (6) ligne d'appel + hashtags optionnels ajoutés à la description (caption) via config. AGENTS.md cite la nouvelle spec dans Décisions ratifiées seulement avec la mention « proposée, à ratifier ». Aucun code.
criteria_by: creator
schema: 4
version: 1
---

Demande utilisateur 2026-09-30 : clips TikTok pour la chaîne Twitch d'une amie (Madajel, jeu d'horreur FR) afin de lui donner de la visibilité. Choix utilisateur (maquette) : « Les deux » = pseudo `twitch.tv/xxx` discret sous le titre d'écran tout le clip + encadré « Abonne-toi ! » les 2 dernières secondes dans la bande du bas. Les réglages vivront dans le CONFIG_DEFAULTS du module de rendu (preset par chaîne via `clipper run <url> --config presets/<chaine>.toml`). Lire SPEC-6127 en entier (ank show SPEC-6127) et ADR-ad2e. La spec reste proposée : seul l'utilisateur la ratifie (ank accept). Preuve de fin : --proof assertion:<id de la spec créée>.
