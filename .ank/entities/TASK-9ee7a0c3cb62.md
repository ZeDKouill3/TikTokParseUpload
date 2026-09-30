---
id: TASK-9ee7a0c3cb62
type: task
slug: sous-titres-rien-l-cran-pendant-les-silences
title: "Sous-titres : rien à l'écran pendant les silences"
created: 2026-09-30T17:14:51Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/subtitles.py
  - tests/test_subtitles.py
  - docs/GUIDE.md
blocked_by: []
done_criteria: |
  Diagnostic consigné (ank log) : d'où vient l'affichage pendant les silences (fin de groupe prolongée jusqu'au groupe suivant, fins de mots whisper étirées sur le silence, durée minimale d'affichage...) mesuré sur les .ass réels de workspace/v2887271276 (copie de travail research/madajel/silences/, jamais workspace/ ni output/ du dépôt) ; correctif : un groupe de mots disparaît au plus tard hold_s (réglable, défaut ~0,3 s) après la fin de son dernier mot ; si l'écart avant le mot suivant dépasse gap_s (réglable, défaut ~0,6 s), rien n'est affiché pendant l'écart ; fins de mots anormalement longues (mot > max_word_s réglable, ex. 1,5 s) bornées ; réglages dans CONFIG_DEFAULTS ; tests unitaires (écart long -> aucun événement .ass couvrant le silence ; mots rapprochés -> pas de clignotement) ; contrôle réel : .ass régénéré pour les 4 clips de la démo, nombre et durée totale des silences désormais vides dans ank log ; valable pour tous les formats (letterbox, stream, split).
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---

Retour utilisateur 2026-09-30 sur les clips de démo : « un souci que je remarque beaucoup : quand ça ne parle pas, il ne faut pas afficher les sous-titres, tu ne mets rien ». Jeu d'horreur : beaucoup de silences et de réactions courtes ; les sous-titres restent affichés pendant les blancs.
