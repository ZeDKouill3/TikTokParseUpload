---
id: TASK-29cfe8ff51a1
type: task
slug: subtitles-zone-s-re-tiktok-placement-hors-visage
title: "subtitles : zone sûre TikTok, placement hors visages et hors accroche, apostrophes"
created: 2026-09-25T19:31:56Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/subtitles.py
  - clipper/pipeline.py
  - tests/test_subtitles.py
  - tests/test_pipeline.py
blocked_by: []
done_criteria: |
  Constats essai réel 2026-09-25 (clip 00) : sous-titres placés tout en haut (sous l'interface TikTok, par-dessus l'accroche) dès que la zone des visages touche le bas, et 'm'a' coupé en 'm' / ''a' entre deux groupes. (1) La position des sous-titres est choisie dans une zone sûre configurée (défaut : entre 20 % et 78 % de la hauteur, hors bande de l'accroche et hors marge droite des icônes), parmi plusieurs hauteurs candidates, en préférant le tiers inférieur de cette zone, et sans recouvrir les visages ; la zone à éviter est calculée par plan à partir du plan de recadrage (pipeline.avoid_zone ou équivalent) et un sous-titre prend la position du plan où il s'affiche ; sans position libre, la moins recouvrante est prise et le fait est journalisé ; (2) un jeton qui commence par une apostrophe ou un trait d'union collé est rattaché au mot précédent pour le regroupement (jamais séparé entre deux groupes) ; tests en parsant le .ass produit (positions par événement, cas split/blur/single, apostrophes) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
