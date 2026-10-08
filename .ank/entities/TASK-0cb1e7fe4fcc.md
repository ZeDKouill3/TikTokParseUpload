---
id: TASK-0cb1e7fe4fcc
type: task
slug: contr-le-webcam-par-clip-le-visage-est-cherch-da
title: "Contrôle webcam par clip : le visage est cherché dans le recadrage agrandi du rectangle, pas sur l'image entière (vraie webcam sans cadre rejetée à tort, 23/24 clips AION en letterbox)"
created: 2026-10-08T14:06:37Z
author: nicoc@zedk_ordi
status: in_progress
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Régression réelle 08/10 après TASK-9957 : v2894178473 (AION 2, twitch-gaming, split) : la webcam est bien localisée (workspace/v2894178473/facecam.json, période 0, rect x251 y831 w264 h188, candidat 7, webcam DÉTOURÉE sans cadre : edge_reason non nul) et le streamer est clairement visible dedans sur les images source (vérifié à l'œil sur 4 instants), mais 23 clips sur 24 passent en letterbox : journal logs/journal-2026-10-08.log « panneau webcam sans visage sur 100% des images clés du clip (0/16 avec un visage dans le rectangle…) » ; seuls 1/19 ou 5/16 visages trouvés. Cause probable (à prouver d'abord, ank-diagnose) : _clip_facecam (contrôle facecam_clip_face_min_share de TASK-9957) lance le détecteur (mediapipe short-range) sur l'image ENTIÈRE 1920x1080 où le visage fait ~60-80 px, souvent penché : le modèle courte portée le rate. (1) Mesurer le taux de détection sur les images clés réelles de v2894178473 : image entière vs recadrage du rectangle (avec marge) agrandi. (2) Corriger : le visage est cherché dans le recadrage agrandi du rectangle (marge et taille réglables dans CONFIG_DEFAULTS), les coordonnées étant ramenées dans le repère de l'image ; mêmes seuils ; ADR-fb9b (détecteur via la fabrique existante, device clipper.gpu, libéré après usage). (3) Les 7 clips du constat de TASK-9957 (v2894232594 00-02 : jeu sans webcam ; v2894088024 03/04/06/09 : webcam déplacée) doivent rester en letterbox : vérifier sur leurs images clés réelles (workspace/ présents) que le recadrage n'y trouve pas de visage là où il n'y en a pas. (4) Tests sans réseau : petit visage dans le rectangle sur grande image -> trouvé via recadrage (détecteur factice sensible à la taille) ; rectangle sans visage -> toujours letterbox. Test réel optionnel skipif sur workspace/v2894178473. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---
