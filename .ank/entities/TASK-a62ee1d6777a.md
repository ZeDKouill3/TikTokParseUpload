---
id: TASK-a62ee1d6777a
type: task
slug: sous-titres-dans-le-bas-de-l-image-en-format-let
title: "sous-titres : dans le bas de l'image en format letterbox"
created: 2026-09-28T17:26:40Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/subtitles.py
  - tests/test_subtitles.py
  - clipper/pipeline.py
  - tests/test_pipeline.py
blocked_by: [TASK-73aca6107f11]
done_criteria: |
  SPEC-6127 : en format letterbox (plan de recadrage layout letterbox), pipeline passe à subtitles la bande verticale du panneau main (haut, bas en fraction de la hauteur de sortie, lue dans reframe/<clip_id>.json) ; subtitles place alors chaque groupe de mots le plus bas possible dans cette bande (marge letterbox_bottom_margin px au-dessus du bas de l'image, CONFIG_DEFAULTS) en évitant les visages retenus comme aujourd'hui, jamais dans les bandes floues, avec une taille de police letterbox_font_size (CONFIG_DEFAULTS, 64 par défaut) au lieu de font_size ; si aucune position de la bande n'évite les visages, le moins recouvrant est pris et c'est journalisé comme aujourd'hui ; hors letterbox, comportement inchangé ; bande absente ou incohérente (hors [0,1], haut >= bas) = erreur explicite. Tests : bande letterbox -> positions toutes dans la bande, au plus bas ; visage retenu en bas de la bande -> texte remonté dans la bande ; taille de police letterbox ; format crop inchangé ; pipeline transmet la bande du panneau main ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
