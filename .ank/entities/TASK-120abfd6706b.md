---
id: TASK-120abfd6706b
type: task
slug: cran-fen-tre-d-alerte-au-clic-publier-valider-qu
title: "Écran : fenêtre d'alerte au clic Publier/Valider quand l'IP n'est pas dans le pays attendu"
created: 2026-10-05T23:13:30Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/web/static/app.js
  - clipper/web/static/ui.js
  - clipper/web/static/style.css
  - clipper/web/static/screens/publish.js
  - clipper/web/static/screens/clips.js
  - clipper/web/static/screens/review.js
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Demande utilisateur 2026-10-05 : quand /api/network renvoie ok=false (pays de l'IP différent du pays attendu, pastille rouge), un clic sur une action qui publie ou programme (« Nouvelle publication » / Publier, Approuver/Valider un clip ou une sélection, Série programmée, Réessayer une publication) ouvre une fenêtre modale d'alerte (pays détecté, pays attendu, « la publication sera refusée / risquée », boutons Annuler et Continuer quand même si le serveur l'autorise sinon seulement Fermer) au lieu de lancer l'action directement. ok=true ou ok=null (inconnu) : comportement inchangé, aucune fenêtre. PAS de notification/popup quand le réseau change (seulement au clic). L'état réseau vient de la dernière valeur de /api/network déjà relevée par app.js (une seule source, pas de nouvel appel réseau obligatoire ; si absente, relever une fois). Aucune logique de traitement côté écran (ADR-09ad) ; le garde-fou serveur existant (08e4846) reste la vraie barrière. Preuves par tests unitaires dans tests/test_web.py (node via _node_run ou contrôle statique) : ok=false -> modale et action non appelée ; ok=true -> action appelée sans modale ; chaque bouton listé passe par la même fonction de garde. Aucun réseau dans les tests.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/8e3c31acd68e@0eef497
    tree: scope/a4a792769dff
    criteria: 86f61d2c1f2d
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
