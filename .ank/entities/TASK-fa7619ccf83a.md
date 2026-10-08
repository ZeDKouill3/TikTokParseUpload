---
id: TASK-fa7619ccf83a
type: task
slug: fiche-par-clip-une-page-qui-rassemble-tout-d-un
title: "Fiche par clip : une page qui rassemble tout d'un clip (vidéo ou fiche seule si la vidéo a été supprimée, jury, passage source, format, QA, posts et leurs stats)"
created: 2026-10-08T13:06:33Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/web/app.py
  - clipper/web/static/screens/clip.js
  - clipper/web/static/screens.js
  - clipper/web/static/app.js
  - clipper/web/static/screens/clips.js
  - clipper/web/static/style.css
  - tests/test_web.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Besoin utilisateur (accord 06/10, confirmé 08/10) : voir sur une seule page tout ce qu'on sait d'un clip, y compris un clip dont la vidéo a été supprimée (« Supprimer la sélection » garde le sidecar .json d'un clip publié, TASK-f909) ou un post déclaré supprimé de la plateforme (TASK-5a7b). (1) Nouvelle route de l'interface (ex. #/clip/<video_id>/<clip_id>) et route API en lecture seule qui rassemble, sans rien recalculer : le sidecar output/<video_id>/<clip_id>.json (titre, légende, score, scores par critère et arguments/trace du jury, raison, hook_text, start/end/durée dans la VOD, layout, qa), la vidéo source (titre, URL avec horodatage du passage), les entrées de publication de ce clip (compte, statut dont removed_from_platform/refused_by_platform, dates Paris, lien du post) et ses relevés de stats (vues, rétention/temps moyen, likes… dans le temps, si présents). (2) Vidéo lue si le .mp4 existe ; sinon mention claire « vidéo supprimée, fiche conservée » (jamais d'erreur ni de lecteur vide). Donnée absente = « inconnu », jamais 0 inventé (ADR-ad2e). (3) Accès depuis l'écran Clips (lien sur chaque clip) et depuis la liste des publications si simple. (4) ADR-09ad : aucune logique de traitement dans clipper/web ; lecture de fichiers et mise en forme seulement. Dates en Europe/Paris. (5) Tests sans réseau : fiche complète ; clip à vidéo supprimée ; clip jamais publié ; post supprimé de la plateforme ; route inconnue -> 404 explicite ; écran servi. CHANGELOG [Non publié] Ajouté.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/1909941ac5fd@6577b81
    tree: scope/56932a68d75d
    criteria: fa0c894ff056
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
