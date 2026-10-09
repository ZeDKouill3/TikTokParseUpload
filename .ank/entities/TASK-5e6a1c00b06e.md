---
id: TASK-5e6a1c00b06e
type: task
slug: worker-jamais-mort-sur-une-exception-inattendue
title: "Worker : jamais mort sur une exception inattendue (apprentissage, répartition, surveillance) et rapprochement à la minute réellement programmée"
created: 2026-10-09T22:43:15Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/worker.py
  - clipper/publish.py
  - tests/test_worker.py
  - tests/test_publish.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Constat et preuve : research/reviews/revue-nuit3.md (local, lis la section citée et le script de preuve sous research/reviews/scratch-revue-nuit3/). (I1) _learning_due, _repartition_due et _watch_channels ne rattrapent qu'une liste d'exceptions : un KeyError/TypeError/AttributeError sous learning.run_if_due ou repartition.run_if_due fait sortir tick() puis loop() : worker mort, plus aucune publication (boucle de crash au redémarrage). Correctif : except Exception final dans ces trois fonctions, journalisé une seule fois par message (log.exception, dédoublonné comme les erreurs existantes), sync.json last_error écrit pour l'apprentissage (via l'API de learning si elle existe, sinon le dire), jamais de propagation hors de tick(). Critère : un learning_runner / repartition_runner / lister de surveillance injecté qui lève KeyError -> Worker.tick() rend sans lever, un seul ERROR journalisé pour deux ticks. (M1) _reconcile_scheduled et _reconcile_to_verify comparent slot_at (minute demandée) au posted_at du relevé, alors que TikTok arrondit la minute au pas de son sélecteur (tiktok.schedule_later) : 09:07 demandé, 09:05 relevé -> undecided même avec une légende unique. Correctif : _reconcile_scheduled utilise entry['tiktok_publish_at'] or slot_at ; pour to_verify, mark_failed(to_verify) enregistre l'heure effective programmée quand elle est connue, sinon la comparaison accepte l'écart au pas de 5 min (jamais plus large) avec légende unique. Critère : entrée slot 09:07, relevé 09:05, légende unique -> found ; deux posts à la même légende dans la fenêtre de 5 min -> undecided (rien conclu). Tests CPU sans réseau. CHANGELOG [Non publié] Corrigé.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/59a273513cd2@6bd6e53
    tree: scope/f4580d531f43
    criteria: 92e7cc8d4262
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
