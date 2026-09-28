---
id: TASK-2fc8e2d95d07
type: task
slug: qa-contr-les-adapt-s-au-format-letterbox-titre-n
title: "qa : contrôles adaptés au format letterbox (titre, noir mesuré dans l'image)"
created: 2026-09-28T17:58:32Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/qa.py
  - tests/test_qa.py
blocked_by: [TASK-b7f4738d62fb]
done_criteria: |
  SPEC-6127. CONTRAT COMMUN (identique dans TASK-e78b, a62e, b7f4 et la tâche qa ; décision utilisateur 2026-09-28 : letterbox sans suivi de visage par défaut ; le format crop (suivi de visage) est gardé en option TEL QUEL, figé : aucun développement dessus, ses tests existants restent verts sans changer leurs assertions) : reframe/<clip_id>.json porte À LA RACINE layout = "letterbox", format = "letterbox" et text_zones = {"title": {"x0","y0","x1","y1"}, "subtitles": {...}, "part": {...}} (entiers, pixels de sortie 1080x1920) ; un seul plan couvre [start, end] : {"index": 0, "start", "end", "image": null, "llm": null, "layout": "letterbox", "reason": null, "faces": [], "panels": [background, main]} ; valeurs par défaut pour une source 1920x1080 : panneau main fenêtre source x=222, y=0, w=1476, h=1080 vers dest x=0, y=440, w=1080, h=790 ; title = (150,160)-(930,424) ; subtitles = (150,1246)-(930,1448) ; part = (150,1464)-(930,1520). Aucun worker ne touche tests/conftest.py ; seul TASK-b7f4 touche pyproject.toml. qa adapte ses contrôles au layout du sidecar. En letterbox (layout = "letterbox" et video_rect présents, écrits par render) : face_cut et subtitle_on_face ne sont plus demandés à l'IA (le zoom rogne volontairement les bords, les sous-titres sont hors de l'image) ; weak_hook est jugé sur screen_title (affiché en permanence, donné dans le prompt à la place du texte d'accroche de 2 s) ; le prompt décrit le format (titre en haut sur encadré blanc, vidéo au centre, sous-titres dessous) ; l'écran noir local (blackdetect) est mesuré sur video_rect seulement (crop ffmpeg avant blackdetect), sinon l'encadré blanc du titre empêche toute détection. layout letterbox sans video_rect = QAError explicite. Hors letterbox, comportement inchangé. Tests : sidecar letterbox -> prompt et schéma sans face_cut ni subtitle_on_face, avec screen_title ; vidéo synthétique letterbox (fond + encadré blanc + noir de 1,5 s dans video_rect) -> black_screen local ; même vidéo avec noir de 0,4 s -> rien ; letterbox sans video_rect -> erreur ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
