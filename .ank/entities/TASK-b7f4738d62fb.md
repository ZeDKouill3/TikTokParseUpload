---
id: TASK-b7f4738d62fb
type: task
slug: render-titre-d-cran-avec-emoji-en-couleur-au-des
title: "render : titre d'écran avec emoji en couleur au-dessus de l'image, « Partie N » dessous (letterbox)"
created: 2026-09-28T17:26:39Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/render.py
  - tests/test_render.py
  - pyproject.toml
blocked_by: []
done_criteria: |
  SPEC-6127 : quand le plan de recadrage a layout letterbox, render lit text_zones dans reframe/<clip_id>.json (text_zones = {"title": {x0,y0,x1,y1}, "subtitles": {x0,y0,x1,y1}, "part": {x0,y0,x1,y1}} en pixels de sortie) et (1) dessine screen_title (lu dans captions.json) pendant tout le clip : texte noir Poppins ExtraBold avec l'emoji en couleur, sur un encadré blanc à coins arrondis (rayon, marges intérieures, taille de police de départ et minimale dans CONFIG_DEFAULTS), centré horizontalement dans la zone title et collé en bas de celle-ci ; le texte passe à la ligne (2 lignes au plus) puis la police est réduite par paliers jusqu'à ce que l'encadré entier tienne dans la zone title ; s'il ne tient pas à la taille minimale = RenderError explicite (jamais tronqué, jamais débordant) ; le titre est rasterisé en PNG transparent avec Pillow (police emoji couleur emoji_font dans CONFIG_DEFAULTS : C:/Windows/Fonts/seguiemj.ttf sous Windows, NotoColorEmoji sous Linux ; police absente = RenderError) puis incrusté par ffmpeg (overlay, sur toute la durée) ; Pillow ajouté aux dépendances de pyproject.toml ; (2) pas d'accroche de 2 s ; (3) « Partie N » (N = part) centré dans la zone part seulement si parts_total > 1, taille qui tient dans la zone (mesurée), sinon RenderError ; (4) écrit screen_title et layout letterbox dans le JSON sidecar. Hors letterbox, rendu inchangé. screen_title absent de captions.json, ou text_zones absent en letterbox = RenderError qui dit quelle étape relancer. Tests : boîte du titre mesurée toujours dans la zone (titre court, titre de 6 mots longs -> 2 lignes, titre impossible -> erreur) ; PNG transparent avec pixels colorés à l'emplacement de l'emoji (skipif police emoji absente) ; filtre ffmpeg (overlay du PNG aux bonnes coordonnées, pas de drawtext d'accroche, Partie seulement si multi-parties) ; rendu ffmpeg réel d'un plan letterbox synthétique (skip si ffmpeg absent) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---
