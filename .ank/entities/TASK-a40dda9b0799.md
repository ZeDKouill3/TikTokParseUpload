---
id: TASK-a40dda9b0799
type: task
slug: console-v2-corrections-du-deuxi-me-tour-qa-objec
title: "console v2 : corrections du deuxième tour (QA [object Object], compteurs, port réel, voyant worker, accents, tri vidéos, pagination stats)"
created: 2026-10-01T10:52:30Z
author: nicoc@zedk_ordi
status: in_progress
scope:
  - clipper/web/app.py
  - clipper/web/__init__.py
  - clipper/web/static/**
  - clipper/__main__.py
  - clipper/worker.py
  - clipper/**/*.py
  - tests/test_web.py
  - tests/test_worker.py
  - tests/test_config.py
blocked_by: []
done_criteria: |
  Tests ciblés, aucun réseau ni GPU, prouvent : (1) Statistiques : les avertissements QA (objets) s'affichent par leur texte lisible, jamais « [object Object] » (test statique sur stats.js : rendu via une fonction qui extrait le message, + test API si la forme vient du serveur) ; (2) un clip refusé par la QA n'est compté ni affiché dans « À valider » : il apparaît dans « Échecs » ou « Refusés » selon SPEC-c1001cb7cbdb, et le compteur du tableau de bord et celui de la page Clips viennent de la même fonction serveur (test : 3 clips dont 1 refusé QA -> 2 à valider partout) ; (3) Réglages > Accès affiche l'hôte et le port réels du serveur en cours (passés par « serve » à l'app), pas ceux de config.toml quand ils diffèrent, et le signale (test API) ; (4) le worker écrit un battement (fichier d'état sous state/ avec pid et horodatage, réglage d'intervalle dans CONFIG_DEFAULTS de worker) ; l'API l'expose ; le tableau de bord affiche un voyant « worker actif / arrêté » avec la commande pour le lancer quand il est arrêté ou que son battement est périmé (tests worker + API + statique dashboard.js) ; (5) les textes d'aide affichés dans Réglages (commentaires des CONFIG_DEFAULTS) sont en français correctement accentué : test qui parcourt les aides exposées par l'API et échoue sur une liste de mots non accentués courants (reponse, refusee, hote, ecoute, defaut, parametre, frequence, etc.) ; ne modifier que des commentaires, aucune valeur ; (6) la liste Vidéos est triée par date d'ajout décroissante (la plus récente en haut), test API ou statique ; (7) le tableau « Résultats par clip » de Statistiques pagine par 50 avec « Afficher plus » (test statique) ; (8) tests existants verts. python -m pytest -q tests/test_web.py tests/test_worker.py tests/test_config.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

Deuxième tour de la console v2 (2026-10-01, après TASK-dc9d) : Statistiques affiche « [object Object] » dans la colonne Contrôle qualité ; tableau de bord 102 clips à valider contre 105 sur la page Clips (3 clips refusés par la QA rangés dans « À valider ») ; Réglages > Accès affiche le port de config.toml (8000) alors que serve tourne sur 8765 ; rien n'indique si le worker tourne (une vidéo mise en file attend sans signal) ; textes d'aide de Réglages sans accents (commentaires des CONFIG_DEFAULTS) ; liste Vidéos triée par identifiant ; tableau des clips de Statistiques non paginé.
