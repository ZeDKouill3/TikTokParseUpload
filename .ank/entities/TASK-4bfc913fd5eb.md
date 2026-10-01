---
id: TASK-4bfc913fd5eb
type: task
slug: console-v2-cinqui-me-tour-saccades-au-rafra-chis
title: "console v2 : cinquième tour (saccades au rafraîchissement, modèle de chaîne et grille visible, libellé de grille, aides lisibles)"
created: 2026-10-01T14:10:01Z
author: nicoc@zedk_ordi
status: in_progress
scope:
  - clipper/web/app.py
  - clipper/web/static/**
  - clipper/**/*.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Tests ciblés, aucun réseau ni GPU, prouvent : (1) SACCADES : un événement SSE ne reconstruit plus tout l'écran quand rien n'a changé : renderCurrent compare le HTML calculé au précédent et ne touche pas au DOM s'il est identique, et l'événement worker (battement) ne met à jour que le voyant du worker ; toutes les vignettes (clips et vidéos) ont une taille réservée (attributs width/height ou aspect-ratio CSS) pour qu'un chargement ne décale jamais la mise en page ; tests statiques ; (2) MODÈLE DE CHAÎNE : à la création d'une chaîne, choix d'un modèle « Standard » ou « Stream gaming » ; « Stream gaming » écrit dans le preset [moments] rubric_path = "builtin:gaming" et l'agencement stream (layout stream_auto, stream_variant split), « Standard » n'écrit rien de plus ; la grille en vigueur est affichée et modifiable directement en haut de la section Chaîne (plus seulement dans la section repliée Grille de notation et moments) ; tests API + statique ; (3) LIBELLÉ DE GRILLE : une valeur rubric_path qui désigne un fichier dont le contenu est identique à la grille standard (ou gaming) embarquée s'affiche « Standard (rubric.toml) » (ou « Gaming (...) ») et non « Fichier personnalisé » ; test API ; (4) AIDES LISIBLES : l'aide d'un réglage affichée dans Chaînes et Réglages commence par une phrase simple destinée à l'utilisateur ; les références techniques (identifiants SPEC-/ADR-/TASK-, noms de fonctions, chemins de code) ne sont plus affichées dans le texte principal (repliées dans un « détails » ou retirées de l'aide exposée) ; test sur l'API d'aide qui échoue si le texte principal contient SPEC-, ADR-, TASK- ou un nom en snake_case suivi de parenthèses ; (5) tests existants verts. python -m pytest -q tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

Séance d'utilisation réelle 2026-10-01 (cinquième tour). Voir les points du critère.
