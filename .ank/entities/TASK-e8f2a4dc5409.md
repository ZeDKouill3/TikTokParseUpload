---
id: TASK-e8f2a4dc5409
type: task
slug: qa-un-clip-stream-split-webcam-en-haut-jeu-en-ba
title: "QA : un clip stream_split (webcam en haut, jeu en bas) est contrôlé selon son vrai format (prompt, accroche, écran noir par panneau)"
created: 2026-10-08T01:53:43Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/qa.py
  - tests/test_qa.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Revue r-adr 08/10 (research/reviews/adr.md M1, preuve research/reviews/scratch-adr/repro_qa_split.py) ; c'est le format du style twitch-gaming utilisé en production. (1) qa.check_clip traite layout stream_split comme un format à panneaux (SPEC-76dc) : le prompt ne parle plus d'un texte d'accroche affiché les 2 premières secondes quand rien n'est dessiné (titre d'écran seulement si title_enabled), et contient une section ## Format décrivant webcam en haut, jeu en bas, badge éventuel entre les deux. (2) blackdetect mesure chaque panneau (webcam_rect, video_rect écrits par render), validés comme _stream_rect ; rectangle absent ou invalide -> erreur explicite (ADR-ad2e), jamais l'image entière en silence. (3) face_cut / subtitle_on_face : demandés seulement s'ils ont un sens en split (au choix documenté, cohérent avec stream). (4) Les formats letterbox, stream, crop ne changent pas (prompts identiques à aujourd'hui). (5) Tests : prompt split sans accroche fantôme et avec ## Format ; blackdetect sur les deux rectangles ; rect manquant -> erreur ; non-régression des prompts letterbox/stream/crop. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 3
---
