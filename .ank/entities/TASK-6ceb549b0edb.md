---
id: TASK-6ceb549b0edb
type: task
slug: comptes-pause-manuelle-d-un-compte-tat-paused-at
title: "Comptes : pause manuelle d'un compte, état paused_at, routes pause/resume, compte en pause jamais tenté ni proposé, stats encore relevables (SPEC-f348 R3 c, R7.1-R7.5)"
created: 2026-10-07T21:01:18Z
author: w-pauseplan
status: done
scope:
  - clipper/accounts.py
  - clipper/worker.py
  - clipper/web/app.py
  - tests/test_accounts.py
  - tests/test_web.py
  - tests/test_worker.py
blocked_by: []
done_criteria: |
  SPEC-f348954318c1 R3 (c), R7.1-R7.5 et la partie serveur de R7.6 tenues, tests sans navigateur ni réseau (tests/test_accounts.py, tests/test_web.py, tests/test_worker.py) : (1) accounts.pause(config, id) pose paused_at (ISO UTC) dans state/accounts.json, relu après rechargement du fichier, décoche ready_to_publish, ready_note et ready_blocked_reason disent « En pause (manuel) depuis le <date> », un message de journal le dit ; un second pause ne change rien ; (2) accounts.resume(config, id) retire paused_at (journalisé) et la case suit R3 : cochée si la connexion est vérifiée et sans arrêt R4, sinon décochée avec la raison de connexion ou d'arrêt (plus celle de pause) ; un resume sans pause ne change rien ; (3) pendant une pause, record_login(connected) et clear_halt laissent ready_to_publish faux avec la raison de pause, et l'arrêt R4 comme l'état de connexion restent enregistrés tels quels ; (4) update_account / PUT /api/accounts/{id} refusent paused_at et ready_to_publish (champ inconnu) ; (5) POST /api/accounts/{id}/pause et POST /api/accounts/{id}/resume existent, réservés au PC comme les autres routes /api/accounts, 404 pour un compte inconnu ; resume revérifie la connexion (fausse lecture de cookies) avant de rendre l'état ; la mise en pause émet l'événement de notification console du décochage ; PUT /api/accounts/{id}/ready répond toujours 405 avec un message qui nomme pause/resume ; GET /api/accounts et GET /api/publish/accounts exposent paused_at et ready_to_publish faux pour un compte en pause ; (6) approuver, programmer, modifier une publication ou programmer une série avec un compte en pause répond 409 et le détail contient « en pause » ; rien n'est approuvé ni mis en file ; (7) le worker ne tente pas une entrée dont le compte est en pause : elle reste scheduled avec une raison visible qui contient « en pause (manuel) », un seul journal/événement par raison, aucun repli vers un autre compte ; après resume avec connexion vérifiée, l'entrée est tentée au tick suivant ; (8) le relevé de stats (GET /api/stats/tiktok et POST /api/stats/tiktok/refresh) ne refuse pas un compte en pause dont la connexion est vérifiée et sans arrêt R4, et le relevé périodique du worker (stats_interval_h > 0) le relève aussi ; (9) python -m pytest -q tests/test_accounts.py tests/test_web.py tests/test_worker.py vert.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/de8344ee0421@f73d0e3
    tree: scope/ea23505a19a3
    criteria: 15751eeda47c
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Implémente R3 (c), R7.1 à R7.5 et la partie serveur de R7.6 de SPEC-f348954318c1 (proposée, successeur de SPEC-e500 : la pause manuelle d'un compte, demande utilisateur du 2026-10-07). Les écrans (accounts.js, clips.js, publish.js) sont la tâche suivante, bloquée par celle-ci.

## Aujourd'hui
- clipper/accounts.py : `ready_blocked_reason(account)` (connexion non vérifiée / expirée, arrêt R4) ; `_sync_ready` recalcule `ready_to_publish` ; `record_login`, `uncheck_ready`, `clear_halt`. Aucune notion de pause.
- clipper/web/app.py : `PUT /api/accounts/{id}/ready` répond 405 (SPEC-e500 R3) ; `_require_ready_account` (409 si pas prêt) ; `_publish_accounts` (GET /api/publish/accounts) ; `_stats_account_info` refuse le relevé d'un compte non prêt ; `_accounts_call` + routes /api/accounts réservées au PC.
- clipper/worker.py : `_account_ready` met l'entrée en attente (`_wait` → `publish.set_waiting_reason`) quand `ready_to_publish` est faux ; relevé périodique des stats (`stats_interval_h`, coupé par défaut) seulement pour un compte prêt.

## À faire (forme attendue, pas imposée au détail)
- accounts.py : champ `paused_at` (ISO UTC ou absent) dans state/accounts.json, exposé par `_public` ; `pause(config, id)` et `resume(config, id)` (idempotents, journalisés, `resume` rend l'état public + `auto_checked`/`auto_unchecked` comme `clear_halt`) ; `ready_blocked_reason` rend d'abord la raison de pause (« En pause (manuel) depuis le <date> : recoche « Prêt à publier » pour reprendre ») ; une fonction séparée (ex. `connection_blocked_reason`) rend la raison connexion/arrêt seule, pour le relevé de stats (R7.5). `_sync_ready` passe par `ready_blocked_reason` : un compte en pause n'est jamais coché, même après `record_login` connecté ou `clear_halt`. `_clean` refuse `paused_at` (champ inconnu, comme `ready_to_publish`).
- app.py : `POST /api/accounts/{id}/pause` et `POST /api/accounts/{id}/resume` (locales, 404 compte inconnu, 202 ou 200 avec l'état public) ; `resume` revérifie la connexion avant de rendre l'état (même mécanique que `_account_resolve`) ; un décochage par pause émet l'événement console comme `_emit_unchecked` ; le 405 de `PUT .../ready` renvoie vers pause/resume ; `_require_ready_account` dit « en pause » quand c'est la raison ; `_publish_accounts` expose `paused_at` ; `_stats_account_info` (et le bouton Relever) ne refuse plus un compte en pause dont la connexion est vérifiée et sans arrêt.
- worker.py : `_account_ready` : raison « compte <libellé> en pause (manuel) depuis le <date> : recoche « Prêt à publier » dans Comptes pour reprendre, ou choisis un autre compte » ; relevé périodique des stats : un compte en pause connecté et sans arrêt reste relevé (R7.5).
- tests : tests/test_accounts.py, tests/test_web.py, tests/test_worker.py ; `test_there_is_no_manual_way_to_tick_ready` et `test_the_manual_ready_route_is_gone_405_with_a_message` sont adaptés (la case ne se force toujours pas à cochée ; le 405 reste, avec le nouveau message).

Heure de Paris pour toute date affichée (SPEC-5e50 R8) ; aucun test ne lance un navigateur ni n'accède au réseau.
