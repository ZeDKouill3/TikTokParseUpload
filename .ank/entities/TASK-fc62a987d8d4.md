---
id: TASK-fc62a987d8d4
type: task
slug: ank-viz-colonnes-et-sections-repliables-d-un-cli
title: "ank-viz : colonnes et sections repliables d'un clic (accordéon)"
created: 2026-09-28T20:00:43Z
author: nicoc@zedk_ordi
status: open
scope:
  - tools/ank-viz/index.html
blocked_by: []
done_criteria: |
  Demande utilisateur 2026-09-28 : dans ank-viz, un clic sur l'en-tête d'une colonne de tâches (En cours, À faire prêtes, bloquées, Faites, Fermées) replie ou déplie sa liste, comme un accordéon ; idem pour le titre de chaque section (Tâches, Dépendances, Branches, Décisions). En-têtes cliquables au clavier (role=button, tabindex, Entrée/Espace), chevron qui pivote, animation courte de la hauteur (désactivée si prefers-reduced-motion). L'état replié survit au rafraîchissement automatique (toutes les 3 s) et au rechargement de la page (localStorage, lu et écrit dans try/catch, la page marche sans) ; par défaut, Faites et Fermées sont repliées. Le compteur de tâches reste visible replié. Aucun changement serveur. Vérification : page servie par tools/ank-viz/server.py, colonnes et sections repliées/dépliées au clic ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
