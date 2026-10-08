---
id: TASK-72c94ce7c9bd
type: task
slug: version-0-6-0-section-changelog-unique-et-compl
title: "Version 0.6.0 : section CHANGELOG unique et complète, numéro de version, zip portable construit"
created: 2026-10-08T21:34:55Z
author: nicoc@zedk_ordi
status: open
scope:
  - CHANGELOG.md
  - pyproject.toml
  - clipper/__init__.py
blocked_by: []
done_criteria: |
  Depuis v0.5.3 (tag, 2026-10-07), 60 fusions de tâches sur main ; la section « ## [Non publié] » de CHANGELOG.md (lignes 11 à ~271) contient des titres en double après des fusions par union (### Ajouté l.13 ET l.151, ### Modifié l.43 ET l.250, ### Corrigé l.66) et des lignes vides parasites. Préférence de l'utilisateur pour une version : UNE seule longue section CHANGELOG complète, aucun fichier de notes séparé. (1) La section [Non publié] devient « ## [0.6.0] - 2026-10-08 », suivie d'une nouvelle section « ## [Non publié] » vide au-dessus ; dans 0.6.0, un paragraphe d'introduction dans le style de celui de 0.5.3 (thèmes de la version : formats stream/webcam (zoom, contrôle par clip, visage dans le recadrage, aucune webcam), styles gaming, fiche clip, alerte 0 vue, préchargement du téléchargement, publication TikTok (fenêtres, interrupteur de vérification, supprimé de la plateforme), veille, vitesse (scenes, tests) ; nom du zip Clipper-portable-0.6.0.zip ; mise à jour en relançant Installer.bat, données non touchées ; liste des NOUVEAUX réglages par table, relevée dans les entrées elles-mêmes), puis UN SEUL ### Ajouté, UN SEUL ### Modifié, UN SEUL ### Corrigé (et ### Retiré s'il y en a) réunissant toutes les entrées existantes : aucune entrée perdue ni réécrite sur le fond (reformulation minimale autorisée seulement pour les doublons exacts, à lister dans le message de commit), compte des puces avant/après donné dans le message de commit. (2) version = "0.6.0" dans pyproject.toml et __version__ = "0.6.0" dans clipper/__init__.py. (3) python tools/build_portable.py construit dist/Clipper-portable-0.6.0.zip sans erreur (chemin et taille dans le pane ; ne pas le committer, dist/ ignoré). (4) Ne PAS créer de tag ni de release GitHub ni pousser : l'orchestrateur s'en charge après fusion. pytest complet vert (ank-done.ps1).
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
