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
blocked_by: []
done_criteria: |
  SPEC-6127 : en format letterbox (plan de recadrage layout letterbox), pipeline passe à subtitles la zone text_zones.subtitles du plan ({x0,y0,x1,y1} en pixels de sortie, écrite par reframe) au lieu des zones de visages et d'accroche ; subtitles place alors chaque groupe de mots dans cette zone : centré horizontalement sur (x0+x1)/2, bloc de texte en haut de la zone, taille letterbox_font_size (CONFIG_DEFAULTS, 68 par défaut) ; chaque groupe est mesuré avec la vraie police (Pillow + clipper/assets/fonts/Poppins-ExtraBold.ttf, contour compris) : s'il est plus large que x1-x0 il est coupé en deux lignes, puis en groupes plus courts, puis la taille est réduite par paliers jusqu'à letterbox_min_font_size ; si un mot seul ne tient toujours pas, erreur explicite ; la hauteur du bloc (2 lignes au plus) doit tenir dans y1-y0, sinon erreur explicite ; jamais de texte hors de la zone, ni dans l'image vidéo ni dans la zone sûre TikTok ; hors letterbox, comportement inchangé ; zone absente ou incohérente = erreur explicite. Tests : groupes normaux dans la zone ; mot très long -> ligne coupée ou taille réduite, toujours dans la zone ; mot impossible -> erreur ; positions/tailles écrites dans le .ass vérifiées contre la zone ; format crop inchangé ; pipeline transmet la zone du plan ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---
