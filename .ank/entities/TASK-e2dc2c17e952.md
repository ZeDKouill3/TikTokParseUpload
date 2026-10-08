---
id: TASK-e2dc2c17e952
type: task
slug: plans-scenes-plus-rapides-d-tection-des-fen-tres
title: "Plans (scenes) plus rapides : détection des fenêtres en parallèle et filtre anti-blocs coupé pour l'analyse"
created: 2026-10-07T23:33:30Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Constat 08/10 (mesures sur VOD 1080p60 h264, PC 12 coeurs) : l'étape scenes prend 25-34 min sur une VOD de 3 h, dominée par le décodage ffmpeg de _detect_scene_list (fenêtres décodées l'une après l'autre) ; 4 ffmpeg en parallèle sur 4x30 s = 10,1 s contre 16,1 s pour 1x120 s ; -skip_loop_filter all en entrée = -9 % ; NVDEC/cuda est PLUS LENT sur ce PC (ne pas l'utiliser). (1) Nouveau réglage CONFIG_DEFAULTS detect_parallel (entier >= 1, défaut 4, refus explicite si < 1 comme extract_parallel) : les fenêtres de _detect_scene_list sont détectées par au plus detect_parallel processus ffmpeg simultanés (ThreadPoolExecutor ou équivalent) ; une fenêtre très longue (> 10 min, seuil réglable detect_chunk_seconds) est découpée en morceaux contigus détectés en parallèle puis recollés, une coupure n'étant jamais inventée à la jointure (fusionner la scène qui chevauche la jointure). Résultat (liste des scènes, ordre) identique au calcul séquentiel sur une même vidéo, hors effet du point 2. (2) Nouveau réglage analysis_skip_loop_filter (booléen, défaut true) : ajoute -skip_loop_filter all à l'entrée ffmpeg de la détection seulement (jamais pour l'extraction des images keyframes, qui restent pleine qualité). (3) Un échec d'un des ffmpeg parallèles fait échouer l'étape avec ScenesError nommant la fenêtre (aucun résultat partiel silencieux, ADR-ad2e) ; les processus restants sont arrêtés. (4) Journal INFO : nombre de fenêtres/morceaux, parallélisme, durée de la détection et de l'extraction séparément. (5) Tests : équivalence séquentiel/parallèle et découpage avec jointure sur une vidéo synthétique ffmpeg lavfi (skipif ffmpeg absent), validation des réglages, échec d'un morceau -> ScenesError, option -skip_loop_filter présente seulement dans la commande de détection. CHANGELOG [Non publié].
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/14d819f7ce6b@aa5ef9a
    tree: scope/e4657ac5a3f8
    criteria: 2eb3d22f4524
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
