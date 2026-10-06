---
id: TASK-3225a4f9df8c
type: task
slug: veille-3-4-choix-des-vod-par-claude-usage-veille
title: "Veille (3/4) : choix des VOD par Claude (usage veille, FakeBackend), relevé quotidien et Rafraîchir par le worker, Clipper/Ignorer, sélection des meilleurs clips du jour avec archivage réversible"
created: 2026-10-06T11:32:40Z
author: w-veille
status: done
scope:
  - clipper/veille.py
  - clipper/worker.py
  - clipper/llm/__init__.py
  - tests/test_veille*.py
  - tests/test_worker*.py
  - tests/test_llm.py
blocked_by: [TASK-97c63be28749]
done_criteria: |
  Veille (3/4), SPEC veille R6, R7 : choix de Claude, exécution par le worker, actions, sélection des meilleurs clips du jour. Tests tests/test_veille.py et tests/test_worker.py avec FakeBackend (jamais le vrai Claude), collecteurs injectés, tmp_path ; aucun réseau. Prouver : (1) decide(day_state, config) fait UN appel llm.ask(usage "veille", texte seul, aucune image) dont le prompt contient taste (ou « aucune préférence déclarée » si vide), max_vods_per_day, chaque candidat avec ses chiffres et deltas ; schéma {picks: [{candidate_id, reason 1-240}] 0..max_vods_per_day, skipped_note 0-300} ; check refuse un candidate_id inconnu ou en double ; une réponse refusée après réparation → llm.status = "error" avec le message, proposals = [], aucune proposition de remplacement ; 0 candidat → llm.status = "skipped" et FakeBackend non appelé ; clipper/llm CONFIG_DEFAULTS usages.veille = {"model": "strong"}. (2) run_if_due(now, config, collectors) : enabled false → aucun fichier écrit ; enabled true, now avant run_at (Europe/Paris) et pas de days/<aujourd'hui>.json → rien ; now ≥ run_at → relevé + décision, days/<date>.json complet avec started_at puis finished_at ; refresh.json présent → relevé rejoué même si le jour existe, refresh.json supprimé avant de commencer, propositions déjà queued/ignored conservées (par candidate_id), les autres remplacées ; le worker l'appelle à chaque tour de boucle (Worker(..., veille_collectors=...) comme watch_lister) et une VeilleError est journalisée une fois sans arrêter le worker. (3) clip(date, candidate_id, channel, short_clips=None, config) → worker.enqueue(url, channel, "run", short_clips=...) ; proposition status "queued" avec queue_entry_id et channel ; seen.queued enrichi ; une 2e fois ou candidat inconnu → VeilleError ; ignore(...) → "ignored" + seen.ignored ; un relevé suivant n'a plus ce video_id en candidat. (4) select_best(now, config) : avec output/<video_id>/ factices (sidecars score, qa.status, series) de deux vidéos de veille done le même jour Europe/Paris et best_clips_per_day = 3 → selection/<date>.json kept = les 3 meilleurs scores (une série multipartie compte pour un, qa rejected jamais retenu), archived = le reste avec rang ; un clip dont l'entrée state/publish est approved/scheduled/published reste kept même hors top ; aucun fichier de output/ n'est modifié ni supprimé (test : mtime et contenu identiques) ; restore(video_id, clip_id) le retire d'archived et l'ajoute à restored ; une vidéo non issue de la veille n'est jamais concernée ; le worker appelle select_best après chaque fin de processus enfant (test avec enfant simulé). pytest vert.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/394dd8d753d0@a2f7aa9
    tree: scope/b2e91c2cb0dc
    criteria: dda1ba3c5c6d
    verifier: tests@904a5eea5add
    via: verifier
  - type: test
    ref: local/01121e88eefc@a2f7aa9
    tree: scope/b2e91c2cb0dc
    criteria: dda1ba3c5c6d
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---

Contexte : ADR ADR-ca9a5792739c (proposé) et SPEC SPEC-bdd9e0db8905 (proposée), planifiés le 2026-10-06 ; maquette research/maquettes/veille.html (local). Lire d'abord clipper/watch.py (même forme de bibliothèque, listeur injecté) et tests/test_watch.py (fixture env). Pour le hook worker, suivre _watch_channels (worker.py) : import local de clipper.veille, erreur journalisée une fois. Pour la sélection, lire les sidecars comme clipper/publish.py (read_sidecar) et les entrées de publication (list_entries) sans modifier output/.
