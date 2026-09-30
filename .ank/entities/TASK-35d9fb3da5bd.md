---
id: TASK-35d9fb3da5bd
type: task
slug: screen-title-le-schema-json-contredisait-encore
title: "screen_title : le schema JSON contredisait encore la regle sans emoji (regression TASK-ab03)"
created: 2026-09-30T12:50:35Z
author: w-ab03e090436c
status: done
scope:
  - clipper/captions.py
  - tests/test_captions.py
blocked_by: []
done_criteria: |
  Revue humaine sur TASK-ab03 (4/4 essais reels avec emoji, 1 rejet apres reparation epuisee) : trouver la cause reelle (response_schema() gardait la description JSON Schema screen_title 'exactement un emoji simple', envoyee a claude -p --json-schema, en contradiction avec le prompt) et la corriger (description coherente avec [captions] screen_title_allow_emoji, aucun emoji par defaut / au plus un si active). Test unitaire prouvant qu'aucun caractere emoji n'apparait dans le prompt NI dans le schema JSON construits quand l'option est off. Controle reel : 4/4 screen_title des 4 moments de workspace/v2887271276 (copie dans research/madajel/titres/, jamais workspace/ ni output/ du depot) acceptes des le premier essai, sans reparation ; budget 8 appels reels au plus.
criteria_by: creator
verify: [tests]
method: diagnose
proof:
  - type: test
    ref: local/f67294330bf6@67b4020
    tree: scope/3abe298ed9e3
    criteria: 80ba0edd47c0
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
