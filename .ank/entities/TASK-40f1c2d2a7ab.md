---
id: TASK-40f1c2d2a7ab
type: task
slug: web-le-temps-r-el-sse-ne-parcourt-plus-les-profi
title: "Web : le temps réel (SSE) ne parcourt plus les profils Chrome et ne bloque plus le serveur"
created: 2026-10-10T18:09:22Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/web/app.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Audit web I3 (research/reviews/audit-1010/web.md, ignoré par git, résumé ici). Constat réel 10/10 : la console met des secondes à charger son contenu ; app.js (24 Ko) servi en 8,6 s, /api/clips en 2,5 s. Cause : _event_stream (app.py ~778-790) appelle _scan_watched (~561-580) de façon SYNCHRONE dans la boucle asyncio à chaque sse_poll_interval_s (1 s) ; _watched_state_roots (~548-558) fait rglob('*.json') sur toute la racine state/, qui contient state/browser/<compte>/ (profils Chrome persistants, ~19 000 entrées, ~1 000 JSON) : 360-400 ms par tour, boucle bloquée ~54 % du temps avec UN onglet, N onglets = N scans. Correctif : (1) ne jamais parcourir le dossier [browser] state_dir (ni d'autre dossier qui n'est pas de l'état surveillé) : racines nommées seulement (fichiers state/*.json et les sous-dossiers d'état réellement affichés en temps réel : publish, repartition, veille, learning, stats si utile — vérifier ce que le JS écoute) ; (2) le scan tourne hors de la boucle (run_in_threadpool / asyncio.to_thread) ; (3) un seul scanner partagé par tous les clients SSE (une tâche, N abonnés), arrêté quand plus aucun client. Aucun événement temps réel existant perdu (tests SSE existants verts). Critère CPU : test de garde où state/browser contient des JSON et _scan_watched/le scanner ne les visite jamais (compteur ou monkeypatch) ; test que deux clients SSE déclenchent un seul scan par intervalle ; mesure avant/après dans ank log du temps d'un tour sur un state/ synthétique de ~20 000 fichiers dont 19 000 sous browser (avant ≥ 10x plus lent qu'après).
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---
