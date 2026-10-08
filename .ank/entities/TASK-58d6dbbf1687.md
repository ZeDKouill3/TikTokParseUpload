---
id: TASK-58d6dbbf1687
type: task
slug: apprentissage-r-tention-par-clip-maturit-dur-e-r
title: "Apprentissage : rétention par clip à maturité (durée, % regardé, source du moment) dans les stats et l'écran Statistiques"
created: 2026-10-08T22:25:07Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/learning.py
  - clipper/web/static/screens/stats.js
  - tests/test_learning.py
  - CHANGELOG.md
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Contexte : research/retention-08-10.md a dû refaire à la main la jointure post -> clip pour mesurer la rétention ; research/reviews/retention-avis.md §4 B′ cadre la suite. Aujourd'hui clipper/learning.py sync écrit déjà avg_watch_s et watched_full dans l'entrée stats de state/outcomes.jsonl (~l.429-432, SPEC-00db R2), seulement pour les relevés mûrs (maturity_days). (1) L'entrée stats ajoute duration (durée du clip lue dans le sidecar output/<video_id>/<clip_id>.json), pct_watched = avg_watch_s / duration (null si l'un des deux manque ou duration <= 0, jamais 0 inventé, ADR-ad2e) et moment_source (transcript | action, lu dans le moment déjà chargé ; null si inconnu). Règles de maturité et d'éligibilité inchangées. (2) learning.status() (GET /api/learning) expose un tableau « rétention à maturité » : une ligne par clip scored (video_id, clip_id, durée, watched_full, pct_watched, views_percentile, moment_source, style si connu), trié par pct_watched décroissant, plus n ; sous [learning] retention_min_n (CONFIG_DEFAULTS, défaut 30) un message explicite « n = X, trop peu pour conclure » ; aucune corrélation calculée. (3) clipper/web/static/screens/stats.js affiche ce tableau (ou le message) dans la partie apprentissage existante, sans logique de calcul côté page (ADR-09ad). (4) retention_min_n invalide (< 1, non entier) = LearningError explicite. (5) Tests sans réseau (fixtures existantes de tests/test_learning.py : _stats_snapshot, _linked_clip, _scored_account) : pct_watched exact (13,38 / 24,47 -> 0,547 à 1e-3), null si avg_watch_s null ou sidecar sans duration ; status() rend le message sous le seuil et le tableau trié au-dessus (30 clips factices) ; idempotence de sync conservée. CHANGELOG [Non publié] Ajouté (réglage nommé).
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---
