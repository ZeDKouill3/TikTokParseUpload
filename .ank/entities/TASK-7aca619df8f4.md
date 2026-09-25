---
id: TASK-7aca619df8f4
type: task
slug: visualiseur-ank-serveur-html-local-t-ches-graphe
title: "Visualiseur ank : serveur HTML local (tâches, graphe de dépendances, branches git)"
created: 2026-09-25T09:39:33Z
author: claude-plan
status: done
scope:
  - tools/ank-viz/**
blocked_by: []
done_criteria: |
  'python tools/ank-viz/server.py' lance un serveur local (bibliothèque standard ou FastAPI) servant une page HTML qui affiche : les tâches groupées en cours / à faire (prêtes ou bloquées) / faites / fermées, avec titre, id, porteur du claim et critère ; les ADR et specs avec leur statut ; le graphe blocked_by dessiné en branches façon git log --graph ; les branches git locales et distantes avec leur dernier commit et leur avance/retard sur main, reliées à la tâche correspondante quand le nom de branche contient l'id ; les données viennent uniquement de la CLI (ank ... --json, git), jamais des fichiers de .ank/ ; la page se rafraîchit seule ; le parsing des sorties ank --json et git est testé sur des sorties enregistrées.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/99b1b78ce2e1@ec791ef
    tree: scope/7bce2aa08e33
    criteria: 486d2c69d317
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Demandé par l'utilisateur pour suivre l'avancement. Outil de dev, hors du paquet clipper. ank a déjà 'ank tui' mais l'utilisateur veut une page web. Respecter la règle ank : .ank/ est opaque, passer par ank find/show/graph/status --json.
