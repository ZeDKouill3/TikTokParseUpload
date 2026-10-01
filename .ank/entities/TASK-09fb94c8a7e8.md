---
id: TASK-09fb94c8a7e8
type: task
slug: web-api-v2-file-de-traitement-journal-relance-an
title: "web API v2 : file de traitement, journal, relance, annulation, chaînes, flux SSE /api/events, jeton d'accès"
created: 2026-09-30T20:43:35Z
author: w-plan-web
status: done
scope:
  - clipper/web/app.py
  - clipper/web/__init__.py
  - tests/test_web.py
blocked_by: [TASK-585e54dc6eab, TASK-bbe4f9df6b56]
done_criteria: |
  tests/test_web.py (TestClient, worker et pipeline simulés par monkeypatch) prouve : (1) POST /api/queue {url, channel|null, action, force_steps} appelle worker.enqueue et renvoie 202 avec l'entrée ; un WorkerError (doublon) donne 409 avec detail en français ; GET /api/queue liste la file ; POST /api/queue/{id}/front et DELETE /api/queue/{id} réordonnent/retirent ; (2) POST /api/videos/{id}/cancel appelle worker.cancel ; POST /api/videos/{id}/retry {from_step} met en file l'action render avec force_steps depuis cette étape ; GET /api/videos/{id}/events renvoie les lignes de events.jsonl (paramètre since) ; (3) GET /api/channels liste les chaînes (channel.list_channels) ; (4) GET /api/events est un flux text/event-stream qui émet un événement {kind, id, at} quand un pipeline.json ou un fichier de state/ change de mtime (test : toucher un fichier pendant la lecture du flux, événement reçu en moins de 2 s) ; (5) jeton : create_app(config) avec [web] host hors bouclage et token vide lève une erreur au démarrage ; avec token, /api/* et /media/* répondent 401 sans jeton et 200 avec l'en-tête X-Clipper-Token ou le cookie ; sur 127.0.0.1 aucun jeton n'est exigé ; (6) test_web_module_only_imports_pipeline_and_config mis à jour : clipper.web n'importe que pipeline, config, channel, worker, publish, watch ; toutes les routes v1 existantes restent vertes. python -m pytest -q tests/test_web.py vert, aucun réseau.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/ec392f390178@5db05b2
    tree: scope/f48bd5c98e6c
    criteria: 1ea5ab4d3ea1
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---

ADR-4f6e §1, §4, §5 ; SPEC-c100 T1, T3, T7 ; SPEC-fc0c §2, §3.2. POST /api/videos (v1) reste et devient un alias de POST /api/queue sans chaîne. clipper/web/__init__.py déclare CONFIG_DEFAULTS pour [web] : host (défaut 127.0.0.1), port (8000), token ("") ; `serve --host/--port` les surchargent.

SSE : un générateur asynchrone qui scrute les mtime (intervalle 1 s, réglage) ; pas de dépendance à un broker. Le flux se teste avec TestClient en mode stream et un délai court. Les publications/surveillance (kind publish/watch) n'ont pas encore de producteur : le flux les émet dès que les fichiers existent.
