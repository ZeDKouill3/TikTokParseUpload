---
id: TASK-f909e2cb48d7
type: task
slug: clips-supprimer-la-s-lection-lib-re-aussi-les-cl
title: "Clips : « Supprimer la sélection » libère aussi les clips déjà publiés (mp4 et annexes lourdes supprimés, sidecar .json gardé pour les stats)"
created: 2026-10-07T22:43:28Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/workspace.py
  - clipper/web/app.py
  - clipper/web/static/screens/clips.js
  - tests/test_workspace.py
  - tests/test_web.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Suite de TASK-2322 (décision utilisateur 08/10) : aujourd'hui delete_clips refuse tout clip déjà publié, l'utilisateur veut libérer la place. (1) clipper.workspace.delete_clips : un clip non publié est supprimé entièrement comme aujourd'hui (mp4, sidecar .json, annexes). Un clip déjà publié (status published dans state/publish) n'est plus refusé : son .mp4 et ses annexes lourdes (tout fichier <clip_id>.* sauf le sidecar <clip_id>.json) sont supprimés, le sidecar .json est GARDÉ intact (lien post -> clip, stats, apprentissage du jury). Un clip programmé, en cours ou en attente de publication reste refusé (PurgeRefused, raison donnée). Tout ou rien par série inchangé : une partie bloquée (programmée, en cours, en attente) refuse toute la série ; dans une série, chaque partie suit sa propre règle (publiée -> sidecar gardé, jamais publiée -> tout supprimé). Le résultat distingue les clips entièrement supprimés et ceux dont seule la vidéo a été supprimée (ex. deleted / video_deleted), octets libérés, journalisé. (2) POST /api/clips/delete rend aussi cette distinction ; aucune logique vidéo dans la route (ADR-09ad). (3) Un clip publié dont le mp4 a été supprimé ne casse aucun écran ni route : vérifier GET /api/clips, l'écran Clips, la fiche d'un clip, Publication et Statistiques (statistiques par post intactes). Dans la liste Clips il n'est plus proposé à la sélection ni lisible (ex. masqué ou marqué « vidéo supprimée », au choix du plus simple et cohérent avec l'existant ), sans erreur ; rerender/approve de ce clip refusés avec un message clair plutôt qu'une erreur 500. (4) clips.js : texte de confirmation adapté (« Les clips publiés gardent leurs infos (stats), seule la vidéo est supprimée. »), toast avec supprimés / vidéos supprimées / refusés et raisons. (5) Tests : publié -> mp4 et annexes supprimés, json intact ; non publié -> tout supprimé ; programmé/en attente/en cours -> refus ; série mixte ; route ; GET /api/clips et fiche sur un publié sans mp4 sans erreur. CHANGELOG [Non publié] (compléter l'entrée « Supprimer la sélection » existante).
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
