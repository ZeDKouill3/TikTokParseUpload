---
id: TASK-a4bf52c1fbff
type: task
slug: veille-historique-1-5-le-relev-de-veille-run-if
title: "Veille historique (1/5) : le relevé de veille (run_if_due) tourne dans un fil d'arrière-plan du processus worker, un seul à la fois, erreur capturée puis journalisée par la boucle ; publications et vidéos continuent pendant le relevé (SPEC-85a0 R26 bis, ADR-6e21 §7)"
created: 2026-10-07T13:14:44Z
author: w-histplan
status: open
scope:
  - clipper/worker.py
  - tests/test_worker.py
blocked_by: []
done_criteria: |
  Tests verts sans réseau (tests/test_worker.py, run_if_due simulé par monkeypatch), pytest complet vert. (1) Worker._veille_due lance veille.run_if_due(now, config, veille_collectors) dans un fil d'arrière-plan du processus worker (threading.Thread, daemon=True, name="veille") et rend la main aussitôt : un test où run_if_due simulé bloque sur un threading.Event vérifie que tick() revient avant la fin du relevé et que la suite de tick (lancement d'un enfant, publication) n'attend pas. (2) Un seul relevé à la fois : tant que le fil vit, un second tick() ne lance ni second fil ni second appel de run_if_due (compteur d'appels = 1). (3) Fil terminé : rejoint au tick suivant ; une VeilleError ou ConfigError levée dans le fil est journalisée une fois par message via _log_veille_error (caplog), le worker continue ; une exception inattendue (ex. RuntimeError) est journalisée avec sa trace (log.exception, caplog montre le type), jamais avalée, le worker continue et un relevé suivant peut repartir. (4) Les collecteurs injectés (veille_collectors) arrivent tels quels au run_if_due du fil ; select_best reste appelé dans la boucle après la fin d'un enfant (tests existants toujours verts, adaptés si besoin au fil). (5) Aucune modification de clipper/veille.py ; aucune ADR ni SPEC amendée.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Constat 07/10/2026 : Worker.tick appelle veille.run_if_due en synchrone ; pendant un relevé (~4 min mesurées, plus avec les sources nouvelles) aucune publication ni vidéo ne démarre. L'utilisateur refuse tout blocage. Précédent dans le même fichier : fil daemon thumbnail-fetch (_start_thumbnail_fetch). Compatible ADR-ca9a (toujours le processus worker) ; processus enfant non retenu (ADR-35b7 réserve les enfants aux vidéos ; collecteurs injectés des tests). Tests existants à adapter : test_tick_calls_veille_run_if_due_with_the_injected_collectors, test_tick_logs_a_veille_error_once_and_keeps_going (joindre le fil avant d'asserter).
