---
id: TASK-8ff9fb648bdd
type: task
slug: cran-vid-os-purge-des-vid-os-termin-es-avec-reto
title: "Écran Vidéos : purge des vidéos terminées avec retour immédiat (calcul, purge en cours, résultat) et calcul de taille plus rapide"
created: 2026-10-09T12:09:33Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/web/static/screens/videos.js
  - clipper/web/app.py
  - clipper/workspace.py
  - tests/test_web.py
  - tests/test_workspace.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Retour de l'utilisateur (09/10) sur le bouton « Purger les vidéos terminées » de l'écran Vidéos (clipper/web/static/screens/videos.js purgeCompleted ~l.232-250 ; routes GET/POST /api/purge-completed clipper/web/app.py ~l.2614-2640 ; calcul clipper/workspace.py heavy_size/_size ~l.116-136, rglob + stat de chaque fichier) : (a) au clic, la fenêtre de confirmation met longtemps à venir et rien ne montre qu'un calcul est en cours ; (b) après « Purger », rien n'indique que la purge tourne jusqu'au toast final : on ne sait pas si ça marche. (1) Retour immédiat au clic : le bouton est désactivé et un état visible « Calcul de l'espace libérable… » (indicateur dans le bouton ou toast persistant) s'affiche pendant le GET ; rétabli en cas d'erreur ou d'annulation. (2) Pendant le POST : une fenêtre ou un toast persistant « Purge en cours… » (non refermable tant que la requête tourne, bouton désactivé), puis le résultat (Go libérés, nombre de vidéos, ignorées) ou l'erreur explicite ; jamais deux purges lancées en double. (3) Mesurer le temps du GET /api/purge-completed actuel sur la vraie console (http://127.0.0.1:8000, GET seulement, AUCUN POST, ne rien purger) et l'écrire dans le log de la tâche ; accélérer le calcul de taille côté serveur sans changer le résultat (ex. os.scandir récursif au lieu de rglob + is_file + stat séparés), même total à l'octet sur un arbre de test ; nouvelle mesure dans le log. (4) Aucune logique de traitement dans la page (ADR-49cd) : le calcul reste côté serveur. (5) Tests CPU sans réseau : _size / heavy_size donnent le même total qu'avant sur un arbre factice (fichiers, sous-dossiers, dossier vide) ; tests/test_web.py vérifie la présence des libellés d'état dans videos.js. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
