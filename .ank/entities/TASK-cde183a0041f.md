---
id: TASK-cde183a0041f
type: task
slug: 3-tests-lents-de-tests-test-pipeline-py-165-s-su
title: "3 tests lents de tests/test_pipeline.py (165 s sur 400 s de suite) : les rendre rapides sans perdre ce qu'ils prouvent"
created: 2026-09-30T07:59:51Z
author: nicoc@zedk_ordi
status: done
scope:
  - tests/test_pipeline.py
blocked_by: []
done_criteria: |
  Les 3 tests test_auto_runs_every_step_queues_a_transient_error_then_finishes (84 s), test_pipeline_pass_journals_every_llm_call_including_from_threads_then_summarizes (42 s), test_review_stops_for_decisions_then_render_resumes (40 s) prennent chacun moins de 5 s (mesure pytest --durations, reportée dans ank log avant/après) ; ils prouvent toujours la même chose (mêmes assertions de comportement, aucune assertion supprimée ni affaiblie) ; aucun changement du code de production ; tests/test_pipeline.py entier passe.
criteria_by: creator
verify: [tests]
method: diagnose
proof:
  - type: test
    ref: local/5db3a9e7e83b@968fcd6
    tree: scope/f7e8b8909594
    criteria: 9117cad75253
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Mesure 2026-09-30 (main c85b56c, `pytest -q --durations=30`) : suite complète 977 tests en 398 s ; ces 3 tests font 84 + 42 + 40 = 165 s. `ank done` relance toute la suite à chaque tâche, donc chaque seconde gagnée ici l'est à chaque clôture.

Diagnostiquer d'abord ce qui coûte (profil : `pytest --durations`, `-p no:randomly`, `cProfile` ou `time.perf_counter` autour des étapes) : vraies attentes (sleep/backoff de la file d'attente transitoire), vrai ffmpeg/rendu de vidéo, vraie transcription/détection, parallélisme réel... Puis remplacer seulement la partie coûteuse par un substitut dans le test (monkeypatch de time.sleep / de l'horloge, réglage de délai via la config du test, étapes lourdes simulées par des fixtures qui écrivent les sorties attendues), en gardant les assertions sur le comportement du pipeline (enchaînement, mise en file puis reprise, journal llm_usage depuis les threads, arrêt en review puis reprise du rendu).

Scope limité à tests/test_pipeline.py (fixtures dans ce fichier, pas dans conftest.py). Si la seule voie propre exige de toucher le code de production (ex. délai de reprise codé en dur hors CONFIG_DEFAULTS), ank release avec la raison exacte au lieu de le faire.
