---
id: TASK-37a3ee2b56c2
type: task
slug: badge-de-cha-ne-fond-optionnel-aucun-et-groupe-l
title: "Badge de chaîne : fond optionnel (aucun) et groupe logo+nom centré"
created: 2026-09-30T15:45:39Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/render.py
  - tests/test_render.py
  - docs/GUIDE.md
blocked_by: []
done_criteria: |
  Nouveau réglage CONFIG_DEFAULTS badge_background (couleur, défaut noir = comportement actuel de SPEC-76dc6a1cbccb inchangé, ou 'none') ; avec 'none' : aucun rectangle derrière le nom, nom avec contour noir + ombre réglables pour rester lisible ; dans tous les cas le groupe logo + espace + nom est centré horizontalement sur le centre de badge_dest (largeur ajustée au contenu mesuré avec la vraie police), plus aucun vide asymétrique ; tests unitaires (géométrie : centre du groupe == centre de badge_dest à 1 px près ; aucun rectangle quand 'none' ; défaut inchangé) ; contrôle réel : preset local research/presets/madajel.toml avec badge_background = 'none', rendu d'une image de 2 clips de workspace/v2887271276 dans une copie de travail research/madajel/badge/ (jamais workspace/ ni output/ du dépôt), captures PNG ; GUIDE mis à jour.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Retour utilisateur 2026-09-30 sur la démo v3 (research/madajel/demo-clips-v3) : « il y a un fond noir derrière le nom, il ne faut pas ; et ce n'est pas centré, trop de noir sur la droite ». Aujourd'hui (render.py ~l.749-770) : carré logo 100 px + nom dans un rectangle noir de badge_dest (420 px) aligné à gauche. SPEC-76dc6a1cbccb décrit le fond noir : il reste le défaut ; on ajoute seulement l'option.
