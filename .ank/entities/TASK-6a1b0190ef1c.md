---
id: TASK-6a1b0190ef1c
type: task
slug: worker-config-plac-avant-la-sous-commande-et-un
title: "worker : --config placé avant la sous-commande, et un enfant qui meurt n'efface plus la vidéo en silence"
created: 2026-10-01T13:51:05Z
author: nicoc@zedk_ordi
status: in_progress
scope:
  - clipper/worker.py
  - tests/test_worker.py
  - clipper/web/app.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Tests de régression d'abord rouges, aucun réseau : (1) _build_command place --config presets/<chaine>.toml AVANT la sous-commande ; test qui passe la commande construite au vrai parseur de clipper.__main__ (parse_args) et vérifie config, action et url/video_id, avec et sans chaîne, avec --force-step ; (2) quand l'enfant se termine avec un code non nul, l'échec est conservé : la vidéo apparaît comme échec (pipeline.json en failed avec raison, créé s'il n'existe pas, ou entrée de file en statut failed exposée par l'API) avec une raison explicite qui contient le code de retour et la fin de la sortie d'erreur de l'enfant ; la sortie de l'enfant est écrite dans un fichier journal (ex. workspace/<id>/worker.log ou state/logs/) au lieu d'être perdue ; le tableau de bord l'affiche dans Échecs (test worker avec spawner simulé + test API) ; (3) un enfant qui se termine avec 0 garde le comportement actuel ; (4) tests existants verts. python -m pytest -q tests/test_worker.py tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 2
---

Séance réelle 2026-10-01 : une vidéo mise en file avec une chaîne (POST /api/queue 202) disparaît : la file se vide, aucun dossier workspace, aucun échec visible. Cause 1 : _build_command (worker.py:223) produit « python -m clipper run <url> --config presets/<chaine>.toml » ; --config est une option globale du parseur, l'enfant meurt sur « clipper: error: unrecognized arguments: --config presets/salur.toml ». Cause 2 : _finish_current ignore le code de retour de l'enfant et retire l'entrée de la file ; un enfant mort avant d'écrire pipeline.json ne laisse aucune trace (contraire à ADR-ad2e).
