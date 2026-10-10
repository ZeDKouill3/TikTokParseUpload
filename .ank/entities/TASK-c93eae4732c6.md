---
id: TASK-c93eae4732c6
type: task
slug: apprentissage-jeu-lu-dans-seen-json-pour-ce-qui
title: "Apprentissage : jeu lu dans seen.json pour « Ce qui marche » et métrique vérifiée avant d'écrire les poids"
created: 2026-10-10T10:03:02Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/learning.py
  - clipper/jury_calibration.py
  - tests/test_learning.py
  - tests/test_jury_calibration.py
blocked_by: []
done_criteria: |
  Deux défauts (revue des merges de la nuit, M1 et M4). (M1) clipper/learning.py _veille_days_games (utilisée par _breakdown) ne lit que state/veille/days/*.json, alors que SPEC-6d1f/SPEC-8a45 font de state/veille/seen.json queued[].game_name la source du jeu d'une VOD mise en file (un jour rejoué remplace les candidats du jour) ; clipper/repartition.py World.veille_games lit seen.json d'abord. Résultat : même VOD rangée « inconnu » dans les statistiques et sous son jeu dans la répartition. Correctif : lire seen.json queued d'abord (même correspondance d'identifiant que repartition : forme brute Twitch et forme v<id>), puis les jours ; sans importer clipper.repartition (ADR-b16b). Critère CPU : une VOD présente dans seen.json queued avec game_name et absente de days/ est rangée sous ce jeu par learning.breakdown ; une VOD présente seulement dans days/ garde son jeu ; régression rouge avant le correctif. (M4) learning._calibrate appelle jury_calibration.calibrate (qui écrit jury_weights.json) AVANT de vérifier qu'au moins une entrée stats porte stats_metric ; avec une métrique absente, les poids appris sont écrasés par 1.0 puis CalibrationError est levée. Correctif : vérifier la présence de la métrique avant tout appel qui écrit. Critère CPU : avec stats_metric = "watched_full" absente de toutes les stats, sync lève l'erreur explicite et jury_weights.json est inchangé octet pour octet (test rouge avant). Aucune valeur de secours silencieuse (ADR-ad2e).
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---
