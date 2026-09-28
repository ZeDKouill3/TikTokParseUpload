---
id: TASK-4f4fe1fa1bf3
type: task
slug: parts-parties-de-60-120-s-qui-se-suivent-chacune
title: "parts : parties de 60-120 s qui se suivent, chacune reprend ~3 s de la précédente"
created: 2026-09-28T20:09:26Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/parts.py
  - tests/test_parts.py
blocked_by: []
done_criteria: |
  SPEC-ef7c (règle 3). parts CONFIG_DEFAULTS gagne part_overlap_seconds = 3, part_overlap_min = 1, part_overlap_max = 8. Pour un moment multipart, une fois les coupes choisies (fin de la partie k = fin de phrase cut_k, comme aujourd'hui), la partie k+1 commence avant cut_k : au début de phrase situé dans [cut_k - part_overlap_max, cut_k - part_overlap_min] le plus proche de cut_k - part_overlap_seconds ; à défaut, au début de mot (mots horodatés de transcript.json) le plus proche de cut_k - part_overlap_seconds dans cette fenêtre ; à défaut (silence), à cut_k - part_overlap_seconds. Jamais au milieu d'un mot. La partie 1 commence au début du moment, la dernière finit à sa fin. Chaque partie, reprise comprise, dure entre part_min - tolerance et part_max + tolerance : le choix des coupes en tient compte (une suite de coupes dont une partie ne tiendrait qu'en ignorant la reprise n'est pas retenue) ; aucune suite possible = rejet motivé, jamais de découpage de secours (ADR-ad2e). Chaque partie de parts.json porte overlap (secondes reprises de la partie précédente, 0 pour la partie 1) et hook_text = texte à partir de son propre début. Le prompt dit que les parties se suivent et que chaque partie reprend environ part_overlap_seconds s de la précédente, et parle de « Partie N » (plus « Part N »). Tests : moment de 6 min -> chaque partie k+1 commence 1 à 8 s avant la fin de la partie k, sur un début de phrase quand il en existe un dans la fenêtre ; repli sur un début de mot ; repli silence ; durées reprise comprise dans les bornes ; rejet motivé quand impossible ; clip unique inchangé (overlap 0) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
