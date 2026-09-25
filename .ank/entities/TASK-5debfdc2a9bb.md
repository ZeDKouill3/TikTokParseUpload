---
id: TASK-5debfdc2a9bb
type: task
slug: ank-viz-afficher-un-premier-tat-en-quelques-seco
title: "ank-viz : afficher un premier état en quelques secondes, les critères ensuite"
created: 2026-09-25T10:04:30Z
author: UP60041549@wl0023729
status: done
scope:
  - tools/ank-viz/**
blocked_by: []
done_criteria: |
  Au démarrage, la page affiche tâches, graphe, branches et décisions dès la première passe rapide (ank find/graph/status + git, sans ank show), puis les critères quand ils arrivent ; une collecte sans critères n'appelle jamais ank show (testé) ; tant que les critères chargent, la page le signale au lieu d'afficher 'aucun critère'.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/8a019b7a88f9@59d1e37
    tree: scope/0ae7f6297409
    criteria: c14bc316381a
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Constaté par l'utilisateur : la page restait ~34 s sur 'première collecte…' car les 19 ank show (~2,5 s chacun) bloquaient la première publication.
