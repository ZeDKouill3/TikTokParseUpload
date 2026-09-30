---
id: TASK-bbe4f9df6b56
type: task
slug: worker-py-file-state-queue-json-processus-enfant
title: "worker.py : file state/queue.json, processus enfant par vidéo, annulation, commandes 'clipper worker' et lancement par 'serve'"
created: 2026-09-30T20:42:23Z
author: w-plan-web
status: done
scope:
  - clipper/worker.py
  - clipper/__main__.py
  - tests/test_worker.py
blocked_by: [TASK-d2348b14bd09]
done_criteria: |
  tests/test_worker.py prouve, sans lancer le vrai pipeline (spawner injecté) : (1) enqueue(url, channel, action, force_steps) écrit une entrée SPEC-fc0c §2.1 dans state/queue.json (atomique), refuse un doublon waiting (même video_id et action) par WorkerError ; move_to_front et remove réordonnent/retirent sans toucher l'entrée running ; (2) tick() lance l'entrée de tête avec la ligne de commande exacte python -m clipper <action> <url|id> [--config presets/<channel>.toml] [--force-step x]... via le spawner, enregistre pid, ne lance rien d'autre tant qu'un enfant vit, retire l'entrée à la fin ; (3) cancel(video_id) termine l'enfant et pipeline.json passe failed avec reason 'annulée par l'utilisateur' ; (4) au démarrage une entrée running dont le pid est mort repasse waiting en tête ; (5) tick() appelle pipeline.process_queue pour les vidéos queued dont retry_at est passé ; (6) python -m clipper worker boucle avec l'intervalle de CONFIG_DEFAULTS et python -m clipper serve lance le worker en sous-processus et l'arrête à la sortie (Popen injecté). python -m pytest -q tests/test_worker.py vert, aucun réseau.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/716833f73698@9d33a52
    tree: scope/f0e7f5187f12
    criteria: 9f7bb6d5b9f0
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---

ADR-4f6e §1, SPEC-fc0c §2. Le worker n'importe que clipper.pipeline, clipper.channel, clipper.watch (quand elle existera) et clipper.config. Un seul enfant à la fois (ADR-fb9b). Terminaison sous Windows : Popen.terminate puis kill après délai ; l'enfant peut être un script python trivial dans les tests.

CONFIG_DEFAULTS de clipper/worker.py : poll_interval_s (défaut 2), cancel_grace_s (défaut 10), queue_path (défaut state/queue.json).
