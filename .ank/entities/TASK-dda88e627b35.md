---
id: TASK-dda88e627b35
type: task
slug: durcissements-de-la-nuit-sse-sans-doublons-journ
title: "Durcissements de la nuit : SSE sans doublons, journal des résultats illisible = erreur explicite, title_repair_attempts validé"
created: 2026-10-09T00:04:51Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/web/app.py
  - clipper/learning.py
  - clipper/captions.py
  - tests/test_web.py
  - tests/test_learning.py
  - tests/test_captions.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  research/reviews/nuit-0910.md M1, M2, M3 (preuves scratch-nuit-0910/p3_sse_roots.py, p6_learning_status_corrupt.py). (1) clipper/web/app.py _watched_state_roots / _scan_watched (~l.549-574) : un même fichier n'est jamais émis deux fois par le flux SSE ; comparaison des dossiers en chemins résolus ; un fichier situé sous une racine à genre fixe ([publish] state_dir, [watch] state_dir) n'est émis qu'avec ce genre fixe, même si la racine de la file le contient aussi. Test : [publish] state_dir absolu désignant state/publish -> un seul élément par fichier ; [publish] state_dir = state/pub2 -> genre « publish », un seul élément. (2) clipper/learning.py _retention (~l.728-735) : une erreur de lecture du journal des résultats (OSError, ValueError dont JSONDecodeError d'une ligne tronquée) devient LearningError nommant le fichier (même traitement que les poids du jury) ; GET /api/learning répond alors l'erreur explicite existante (422) et non un 500. Test : journal avec une ligne tronquée -> LearningError ; via l'API -> 422 avec le nom du fichier. (3) clipper/captions.py : [captions] title_repair_attempts validé en tête d'étape (entier >= 0, bool refusé) avec CaptionsError nommant le réglage ; plus de int() qui tronque 2.7 en silence. Test : 2.7, "abc", True, -1 -> CaptionsError ; 0 et 3 acceptés. Tout CPU, sans réseau, FakeBackend. CHANGELOG [Non publié] Corrigé (une ligne par point).
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/152ce2db6165@c753e7d
    tree: scope/ea7730e791a3
    criteria: 473c95797415
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
