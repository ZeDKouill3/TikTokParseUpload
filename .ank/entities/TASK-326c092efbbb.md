---
id: TASK-326c092efbbb
type: task
slug: tape-parts-d-coupage-en-part-1-2-3-avec-fins-en
title: "Étape parts : découpage en Part 1/2/3 avec fins en suspense"
created: 2026-09-25T09:39:42Z
author: claude-plan
status: done
scope:
  - clipper/parts.py
  - tests/test_parts.py
blocked_by: [TASK-68811e08394e]
done_criteria: |
  Pour chaque moment retenu, l'étape décide clip unique (20-45 s) ou N parties (60-90 s, bornes de rubric.toml) ; les points de coupe sont proposés par clipper.llm (usage parts) puis recalés sur la fin de phrase la plus proche ; aucune partie hors bornes, aucune coupe au milieu d'un mot, les parties couvrent le moment sans trou ni chevauchement (testé) ; résultat dans workspace/<video_id>/parts.json.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/9920e509846f@c652b97
    tree: scope/a1eb7c77d962
    criteria: 17edf9739643
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
