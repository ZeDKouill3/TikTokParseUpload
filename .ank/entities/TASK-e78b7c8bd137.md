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
  - config.example.toml
blocked_by: []
done_criteria: |
  SPEC-6127. CONTRAT COMMUN (identique dans TASK-e78b, a62e, b7f4 et la tâche qa ; décision utilisateur 2026-09-28 : letterbox sans suivi de visage par défaut ; le format crop (suivi de visage) est gardé en option TEL QUEL, figé : aucun développement dessus, ses tests existants restent verts sans changer leurs assertions) : reframe/<clip_id>.json porte À LA RACINE layout = "letterbox", format = "letterbox" et text_zones = {"title": {"x0","y0","x1","y1"}, "subtitles": {...}, "part": {...}} (entiers, pixels de sortie 1080x1920) ; un seul plan couvre [start, end] : {"index": 0, "start", "end", "image": null, "llm": null, "layout": "letterbox", "reason": null, "faces": [], "panels": [background, main]} ; valeurs par défaut pour une source 1920x1080 : panneau main fenêtre source x=222, y=0, w=1476, h=1080 vers dest x=0, y=440, w=1080, h=790 ; title = (150,160)-(930,424) ; subtitles = (150,1246)-(930,1448) ; part = (150,1464)-(930,1520). Aucun worker ne touche tests/conftest.py ; seul TASK-b7f4 touche pyproject.toml. CONFIG_DEFAULTS de reframe gagne : format = letterbox | crop (letterbox par défaut ; crop = code actuel inchangé), letterbox_zoom = 1.3, letterbox_top = 440, safe_top = 160, safe_bottom = 1520, safe_left = 150, safe_right = 930, text_gap = 16, part_height = 56 (documentés comme pensés pour une source 16:9). En letterbox : aucune détection de visage, aucun détecteur construit, aucun appel LLM, scenes.json non requis ; taille source lue sans détecteur (OpenCV ou ffprobe). Géométrie déterministe : w = round(source_w / zoom), moins 1 si impair ; x = (source_w - w) // 2 ; h = round(source_h * 1080 / w), moins 1 si impair ; main = fenêtre (x, 0, w, source_h) vers dest (0, letterbox_top, 1080, h) ; background = source entière, effect blur, vers (0, 0, 1080, 1920). Zones : title = (safe_left, safe_top)-(safe_right, letterbox_top - text_gap) ; subtitles = (safe_left, letterbox_top + h + text_gap)-(safe_right, safe_bottom - part_height - text_gap) ; part = (safe_left, safe_bottom - part_height)-(safe_right, safe_bottom). Zone vide ou inversée, hors 1080x1920, ou qui chevauche l'image vidéo = ReframeError explicite (ex. source 4:3 avec les défauts) ; zoom < 1 ou format inconnu = ReframeError. Un plan déjà présent dont le format diffère de la config (sans champ format = ancien crop) n'est pas réutilisé en silence : ReframeError qui demande --force (ADR-ad2e). config.example.toml documente [reframe] format et letterbox_zoom. Tests : source 1920x1080 -> valeurs exactes du contrat ; source 1280x720 -> fenêtre 984x720 à x=148 vers 1080x790 ; source 1440x1080 -> ReframeError de zones ; aucun appel LLM (FakeBackend sans réponse) ni détecteur construit ; plan existant crop avec config letterbox -> erreur, avec force -> recalculé ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 3
---
