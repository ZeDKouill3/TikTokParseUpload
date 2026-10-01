---
id: TASK-ded3a1f27c57
type: task
slug: lot-1-web-v2-verrou-inter-processus-sur-state-pr
title: "lot 1 web v2 : verrou inter-processus sur state/, preset de chaîne à la reprise, garde-fous de statut dans publish"
created: 2026-10-01T08:26:34Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/worker.py
  - clipper/publish.py
  - clipper/pipeline.py
  - clipper/channel.py
  - tests/test_worker.py
  - tests/test_publish.py
  - tests/test_pipeline_state.py
  - tests/test_channel.py
blocked_by: []
done_criteria: |
  Tests ciblés, aucun réseau, prouvent : (1) chaque cycle lecture-modification-écriture de state/queue.json (worker) et de state/publish/<chaine>.json (publish) se fait sous un verrou de fichier inter-processus portable Windows/Linux (stdlib uniquement : msvcrt/fcntl, aucune nouvelle dépendance) avec écriture atomique (fichier temporaire + os.replace) ; test : 2 processus (multiprocessing) qui font chacun 20 worker.enqueue (resp. 20 approve dans publish) en parallèle, aucune entrée perdue ; (2) pipeline.process_queue, pour un état dont channel n'est pas null, recharge le preset de cette chaîne (channel.load_channel) et relance avec cette config, pas la config globale (test par monkeypatch : le mode de la chaîne s'applique) ; une chaîne disparue donne une erreur journalisée et la vidéo reste en attente, jamais un repli silencieux sur la config globale ; (3) publish.move refuse une entrée rejected ou published, publish.mark_published exige status scheduled : PublishError explicite en français, testés ; (4) approve d'une partie N>1 d'une série dont la partie N-1 n'est ni approved ni scheduled lève PublishError (ordre des créneaux garanti) ; (5) channel.list_channels sur un preset TOML malformé lève ChannelError nommant le fichier ; publish._sibling_clip_ids sur un JSON corrompu lève PublishError ; (6) les tests existants de test_worker, test_publish, test_pipeline_state, test_channel restent verts. python -m pytest -q tests/test_worker.py tests/test_publish.py tests/test_pipeline_state.py tests/test_channel.py vert.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/e6dec0da570f@2924171
    tree: scope/4fa0dc579efb
    criteria: 1c286d3706ed
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Relecture du lot 1 (2026-10-01) : le worker et l'API web sont deux processus (ADR-4f6e) qui réécrivent state/queue.json et state/publish/<chaine>.json sans verrou ; process_queue relance les vidéos en attente avec la config globale au lieu du preset de leur chaîne (SPEC-fc0c §1.3) ; publish.move/mark_published acceptent des statuts incohérents ; erreurs brutes sur TOML/JSON corrompu (ADR-ad2e).
