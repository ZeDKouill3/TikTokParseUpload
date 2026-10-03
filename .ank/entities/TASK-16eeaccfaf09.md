---
id: TASK-16eeaccfaf09
type: task
slug: s-rie-programm-e-le-mode-automatique-pioche-seul
title: "Série programmée : le mode automatique pioche seulement dans les clips validés (approuvés, pas encore planifiés) du compte choisi"
created: 2026-10-03T19:03:54Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/publish.py
  - clipper/web/app.py
  - clipper/web/static/screens/publish.js
  - tests/test_publish.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Tests rouges puis verts, sans réseau : mode auto de preview_series/create_series = uniquement des unités dont TOUTES les parties ont une entrée de publication 'approved' sans créneau (slot_at None, pas en cours) et dont le compte est celui de la série (ou aucun) ; un clip prêt mais non validé n'est jamais pris en auto ; un clip validé pour un autre compte non plus ; tri par score, parties ensemble dans l'ordre, refus explicites inchangés ; création = ces entrées approuvées passent en programmé aux dates de la série (create_post accepte déjà 'approved'), tout ou rien conservé. Mode manuel : propose les clips validés ET les clips prêts non validés (comme aujourd'hui), avec une marque « validé » visible. Message clair si aucun clip validé (« valide d'abord des clips dans l'écran Clips »). Texte du formulaire en auto : « N vidéos validées seront choisies, par score décroissant ».
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/b92ef257d186@9bc042b
    tree: scope/f6bda1b8370f
    criteria: 44fd80dfa3c3
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Demande utilisateur 2026-10-03 : « les vidéos auto doivent être parmi le pool des vidéos validées ». Aujourd'hui available_series_clips/_eligible_units prennent les clips ready absents de toute file, donc justement PAS les clips approuvés. Une autre tâche (TASK-4c3d) modifie publish.py et app.py en parallèle (approve, approbation groupée, set_channel) : reste localisé sur la série.
