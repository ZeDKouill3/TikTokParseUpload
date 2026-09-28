---
id: TASK-e78b7c8bd137
type: task
slug: reframe-format-letterbox-image-horizontale-zoom
title: "reframe : format letterbox (image horizontale zoomée sur fond flou), sans appel LLM"
created: 2026-09-28T17:26:11Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
blocked_by: []
done_criteria: |
  SPEC-6127 (format letterbox simple, décision utilisateur 2026-09-28 : pas de suivi de visage). CONFIG_DEFAULTS de reframe gagne : format = letterbox | crop (letterbox par défaut ; crop = comportement actuel inchangé), letterbox_zoom = 1.3, letterbox_top = 440, safe_top = 160, safe_bottom = 1520, safe_left = 150, safe_right = 930, text_gap = 20, part_height = 70. En letterbox : aucune détection de visage, aucun appel LLM, pas de mediapipe chargé ; pour tout le clip un seul plan (ou un par plan de scenes, au choix documenté) avec layout = letterbox, panneaux background (effect blur, source entière vers 0,0,1080,1920) puis main (fenêtre source centrée de largeur round(source_w / zoom) paire, pleine hauteur, vers dest x=0, y=letterbox_top, w=1080, h=hauteur au prorata arrondie au pair) ; faces = [] ; le plan JSON gagne text_zones = {"title": {x0,y0,x1,y1}, "subtitles": {x0,y0,x1,y1}, "part": {x0,y0,x1,y1}} en pixels de sortie : title = [safe_left, safe_top] -> [safe_right, letterbox_top - text_gap] ; subtitles = [safe_left, bas de l'image + text_gap] -> [safe_right, safe_bottom - part_height - text_gap] ; part = [safe_left, safe_bottom - part_height] -> [safe_right, safe_bottom] ; zone vide, inversée, hors 1080x1920 ou qui chevauche l'image vidéo = ReframeError explicite ; zoom < 1 ou format inconnu = ReframeError. Même format JSON qu'aujourd'hui pour le reste (render le lit sans changement). Tests : source 1920x1080 -> fenêtre 1476x1080 centrée (x=222), dest 1080x790 à y=440, zones exactes ; source 1280x720 ; zones incohérentes (letterbox_top trop bas) -> erreur ; aucun appel LLM (FakeBackend sans réponse) ni détecteur construit ; format crop inchangé ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---
