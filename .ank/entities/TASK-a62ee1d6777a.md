---
id: TASK-a62ee1d6777a
type: task
slug: sous-titres-dans-le-bas-de-l-image-en-format-let
title: "sous-titres : dans le bas de l'image en format letterbox"
created: 2026-09-28T17:26:40Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/subtitles.py
  - tests/test_subtitles.py
  - clipper/pipeline.py
  - tests/test_pipeline.py
blocked_by: []
done_criteria: |
  SPEC-6127. CONTRAT COMMUN (identique dans TASK-e78b, a62e, b7f4 et la tâche qa ; décision utilisateur 2026-09-28 : letterbox sans suivi de visage par défaut ; le format crop (suivi de visage) est gardé en option TEL QUEL, figé : aucun développement dessus, ses tests existants restent verts sans changer leurs assertions) : reframe/<clip_id>.json porte À LA RACINE layout = "letterbox", format = "letterbox" et text_zones = {"title": {"x0","y0","x1","y1"}, "subtitles": {...}, "part": {...}} (entiers, pixels de sortie 1080x1920) ; un seul plan couvre [start, end] : {"index": 0, "start", "end", "image": null, "llm": null, "layout": "letterbox", "reason": null, "faces": [], "panels": [background, main]} ; valeurs par défaut pour une source 1920x1080 : panneau main fenêtre source x=222, y=0, w=1476, h=1080 vers dest x=0, y=440, w=1080, h=790 ; title = (150,160)-(930,424) ; subtitles = (150,1246)-(930,1448) ; part = (150,1464)-(930,1520). Aucun worker ne touche tests/conftest.py ; seul TASK-b7f4 touche pyproject.toml. En format letterbox (plan de recadrage avec layout = "letterbox" à la racine), pipeline passe à subtitles la zone text_zones.subtitles de la racine du plan (au lieu des zones de visages et d'accroche) ; hors letterbox, comportement inchangé. subtitles place alors chaque groupe de mots dans cette zone, texte en MAJUSCULES (letterbox_uppercase = true dans CONFIG_DEFAULTS, maquette validée), taille letterbox_font_size = 68 exprimée en pixels d'em (comme Pillow et la maquette) ; la valeur écrite dans le Fontsize du .ass est round(size * (usWinAscent + usWinDescent) / unitsPerEm), lus dans la police avec fontTools (1,762 pour Poppins ExtraBold : Fontsize ≈ 120 pour 68) ; interligne letterbox_line_height = 1.15 em. Chaque groupe est mesuré avec Pillow à la taille em (clipper/assets/fonts/Poppins-ExtraBold.ttf, contour compris) : plus large que x1 - x0 -> coupé en deux lignes, puis en groupes plus courts, puis taille réduite par paliers jusqu'à letterbox_min_font_size ; un mot seul qui ne tient pas = erreur explicite ; 2 lignes au plus. INTERLIGNE (constat mesuré par le worker le 2026-09-28 : libass avance chaque \N de Fontsize = 1,762 em, non réglable ; \N est donc INTERDIT en letterbox) : chaque ligne est un événement Dialogue distinct (mêmes start/end), sans \N, avec {\q2}, alignement \an8, MarginL = x0, MarginR = 1080 - x1, MarginV = y0 + i x pas pour la ligne i (0 ou 1), pas = round(letterbox_line_height x em) (78 px pour 68, comme la maquette). Hauteur vérifiée comme libass la dessine : ligne de base de la ligne i = y0 + i x pas + round(em x usWinAscent / unitsPerEm) ; bas d'encre = ligne de base de la dernière ligne + descente d'encre mesurée par Pillow sur le texte (bbox ancrée sur la ligne de base) + contour, doit être <= y1, sinon groupe plus court ou taille réduite, puis erreur explicite. Le .ass letterbox commence par un commentaire « ; format: letterbox » ; un .ass existant d'un autre format n'est pas réutilisé en silence (erreur qui demande --force). Zone absente ou incohérente = erreur explicite. Tests : deux lignes à la taille par défaut tiennent dans la zone par défaut ; mot très long -> coupe ou réduction, toujours dans la zone ; mot impossible -> erreur ; Fontsize, absence de \N, \q2, \an8, marges et MarginV de chaque ligne du .ass vérifiés contre la zone ; pipeline transmet text_zones.subtitles ; PREUVE PAR RENDU RÉEL (test sauté si ffmpeg est absent du PATH, lancé en local) : ffmpeg + libass incruste sur fond noir 1080x1920 un groupe de deux lignes à la taille par défaut avec jambages et virgules (ex. « ÇA VA, QUOI ? » / « JE PENSE QUE OUI, ») ; toute l'encre claire mesurée est dans la zone subtitles (x et y) et l'écart entre les deux lignes vaut le pas à ± 4 px près ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/cf3916695181@6a644a4
    tree: scope/8841b81e0816
    criteria: 722c3729a42d
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 10
---
