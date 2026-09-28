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
  SPEC-6127. CONTRAT COMMUN (identique dans TASK-e78b, a62e, b7f4 et la tâche qa ; décision utilisateur 2026-09-28 : letterbox sans suivi de visage par défaut ; le format crop (suivi de visage) est gardé en option TEL QUEL, figé : aucun développement dessus, ses tests existants restent verts sans changer leurs assertions) : reframe/<clip_id>.json porte À LA RACINE layout = "letterbox", format = "letterbox" et text_zones = {"title": {"x0","y0","x1","y1"}, "subtitles": {...}, "part": {...}} (entiers, pixels de sortie 1080x1920) ; un seul plan couvre [start, end] : {"index": 0, "start", "end", "image": null, "llm": null, "layout": "letterbox", "reason": null, "faces": [], "panels": [background, main]} ; valeurs par défaut pour une source 1920x1080 : panneau main fenêtre source x=222, y=0, w=1476, h=1080 vers dest x=0, y=440, w=1080, h=790 ; title = (150,160)-(930,424) ; subtitles = (150,1246)-(930,1448) ; part = (150,1464)-(930,1520). Aucun worker ne touche tests/conftest.py ; seul TASK-b7f4 touche pyproject.toml. Quand reframe/<clip_id>.json a layout = "letterbox" à la racine, render lit text_zones et (1) dessine screen_title (lu dans captions.json) pendant tout le clip : texte noir Poppins ExtraBold et emoji en couleur, sur un encadré blanc à coins arrondis (rayon, marges intérieures, taille de départ et minimale dans CONFIG_DEFAULTS), centré horizontalement dans la zone title et collé en bas de celle-ci ; le texte est découpé en segments texte / emoji par classe Unicode (texte en Poppins, emoji en emoji_font) ; il passe à la ligne (2 lignes au plus) puis la taille baisse par paliers jusqu'à ce que l'encadré entier tienne dans la zone title ; s'il ne tient pas à la taille minimale = RenderError explicite (jamais tronqué, jamais débordant). Le titre est rasterisé en PNG transparent avec Pillow puis incrusté par ffmpeg (deuxième entrée -i, overlay sur toute la durée) ; emoji_font résolu par plateforme et documenté (Windows : C:/Windows/Fonts/seguiemj.ttf ; Linux : NotoColorEmoji.ttf, qui ne s'ouvre qu'à la taille 109 : rasteriser à 109 puis réduire) ; police absente = RenderError ; Pillow et fonttools ajoutés aux dépendances de pyproject.toml. (2) Pas d'accroche de 2 s en letterbox. (3) « Partie N » (N = part) centré dans la zone part seulement si parts_total > 1 (drawtext, taille en em comme Pillow, mesurée pour tenir dans la zone, sinon RenderError). (4) Le sidecar JSON porte toujours screen_title (tous formats ; absent de captions.json = RenderError qui demande de relancer captions --force) et, en letterbox, layout = "letterbox" et video_rect = {x, y, w, h} (le panneau main en pixels de sortie, pour la qa). Hors letterbox, rendu inchangé. text_zones absent en letterbox = RenderError qui dit de relancer reframe. Tests : encadré mesuré toujours dans la zone (titre court ; 6 mots longs -> 2 lignes ; titre impossible -> erreur) ; PNG transparent avec pixels colorés à l'emplacement de l'emoji (skipif police emoji absente) ; filtre ffmpeg (overlay du PNG aux bonnes coordonnées, pas de drawtext d'accroche, Partie seulement si multi-parties) ; sidecar avec screen_title et video_rect ; rendu ffmpeg réel d'un plan letterbox synthétique (skip si ffmpeg absent) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 5
---
