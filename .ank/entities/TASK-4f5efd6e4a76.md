---
id: TASK-4f5efd6e4a76
type: task
slug: clips-courts-interrupteur-on-off-par-style-et-pa
title: "Clips courts : interrupteur on/off (par style et par vidéo) 20-45 s, clip qui démarre sur le moment fort"
created: 2026-10-06T10:55:13Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/moments.py
  - clipper/worker.py
  - clipper/pipeline.py
  - clipper/__main__.py
  - clipper/cli.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_moments*.py
  - tests/test_worker*.py
  - tests/test_pipeline*.py
  - tests/test_cli*.py
  - tests/test_web*.py
  - CHANGELOG.md
  - docs/GUIDE.md
blocked_by: []
done_criteria: |
  Contexte 2026-10-06 : premier post TikTok manuel (clip 92 s) = 142 vues, temps moyen 18 s, 3,9 % de visionnage complet -> clips trop longs, accroche trop lente. Les durées viennent aujourd'hui de la grille ([durations] : rubric.toml 60-120 s, rubric-gaming.toml 30-90 s). Livrer un INTERRUPTEUR « clips courts » : (1) réglage [moments] short_clips (bool, défaut false) dans CONFIG_DEFAULTS de clipper/moments.py, donc activable par style (presets/<style>.toml [moments] short_clips = true) ou config.toml ; réglages associés dans le même dict (ex. short_min = 20, short_max = 45 s pour clip unique ET parties de série). (2) par vidéo : case à cocher « Clips courts » dans le formulaire Nouvelle vidéo de l'interface web ; trois états effectifs : non précisé = valeur du style, coché = on, décoché explicitement = off ; la valeur voyage dans l'entrée de file (POST /api/queue, champ optionnel, rétrocompatible : anciennes entrées sans le champ = valeur du style) jusqu'au processus de la vidéo (option CLI ou équivalent, jamais d'import de clipper.web par une étape, ADR-b16b). (3) quand actif : les bornes de durée de la grille sont remplacées par short_min/short_max, et la consigne donnée à Claude pour les moments exige que le clip démarre directement sur le moment fort (accroche dans les 2 premières secondes, pas de mise en place), tout en restant compréhensible seul ; quand inactif : comportement STRICTEMENT identique à aujourd'hui (test qui le prouve). (4) le mode utilisé est écrit dans moments.json et visible sur la fiche vidéo. (5) aucun repli silencieux (ADR-ad2e) : valeur invalide = erreur explicite. CHANGELOG [Non publié] + docs/GUIDE.md mis à jour. Tests unitaires avec FakeBackend (jamais le vrai Claude), aucun réseau. Ne pas toucher clipper/reframe.py (autre tâche en parallèle).
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---
