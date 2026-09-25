---
id: TASK-e4938e2a7fc3
type: task
slug: moments-apr-s-vision-re-noter-les-candidats-exis
title: "moments : après vision, re-noter les candidats existants au lieu de refaire la sélection"
created: 2026-09-25T18:26:54Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/moments.py
  - clipper/pipeline.py
  - tests/test_moments.py
  - tests/test_pipeline.py
blocked_by: []
done_criteria: |
  Constat essai réel 2026-09-25 (sZi-qJ-5ptA) : après vision, pipeline relance moments avec force, ce qui redemande toute la sélection au LLM ; Claude a renvoyé une liste différente (9 -> 11 moments, autres bornes). Quand moments.json existe et que vision.json est plus récent, l'étape recalcule seulement le bonus visuel, le score final, le filtre min_score et le non-chevauchement sur les candidats déjà enregistrés (retenus et rejetés pour score), sans aucun appel LLM ; les notes par critère, les bornes et les justifications restent identiques ; un moment rejeté pour score peut passer retenu si le bonus le fait atteindre min_score, et moments.json indique quels moments ont changé ; le premier passage (sans moments.json) reste inchangé ; tests avec FakeBackend qui échoue s'il est appelé pendant la re-notation ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/b2c8f4d2e12e@81e88d8
    tree: scope/861063c27ac4
    criteria: 66f753625721
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Le bonus visuel est mécanique (rubric.toml [bonus] visual si une image du moment est striking dans vision.json) : aucune raison de redemander le jugement du LLM. Vision a déjà été limitée aux candidats rattrapables (TASK-1a2b).
