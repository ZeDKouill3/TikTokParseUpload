---
id: TASK-9c7f45092ddc
type: task
slug: r-partition-automatique-1-5-biblioth-que-clipper
title: "Répartition automatique (1/5) : bibliothèque clipper/repartition.py, calcul du plan et fichier d'état (SPEC-78dc R0-R7)"
created: 2026-10-09T13:09:00Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/repartition.py
  - tests/test_repartition.py
  - config.example.toml
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  SPEC-78dc4a8c1c3b R0 à R7 (lire la spec en entier : ank show SPEC-78dc4a8c1c3b). Nouvelle bibliothèque clipper/repartition.py (pas une étape : n'importe ni clipper.web ni une étape ; importe publish, accounts, tiktok, channel) : CONFIG_DEFAULTS [repartition] exactement comme R0 ; compute_plan(day, now, config=) et run_if_due(now, config=) ; fichier state/repartition/<AAAA-MM-JJ>.json atomique sous verrou (R7). Réutiliser publish.available_series_clips, accounts.schedule_of, channel.next_slots, publish.planned_times, tiktok.read_history / merged_posts (voir research/drafts/plan-repartition-auto.md §0). Décisions utilisateur du 09/10 : séries en plusieurs parties exclues entièrement du vivier (R2) ; jeu inconnu -> regroupement par VOD (R3) ; calcul à 20:00 (compute_time), jamais de validation automatique. Critère : python -m pytest -q tests/test_repartition.py vert, sans réseau ni GPU, avec au moins un test par règle R0-R7 (liste de R10 de la spec) ; compute_plan rend un fichier déterministe hors computed_at ; run_if_due ne calcule qu'après compute_time et jamais deux fois pour le même jour ; test de garde ast : clipper/repartition.py n'importe ni clipper.web ni un module de pipeline.STEPS ; config.example.toml documente [repartition] ; aucun nom réel de compte ou de chaîne dans le code, les tests et les entités. CHANGELOG [Non publié] Ajouté.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/c814ebc084f5@f64783b
    tree: scope/bb42e6b4877c
    criteria: fefaf3fa1e91
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
