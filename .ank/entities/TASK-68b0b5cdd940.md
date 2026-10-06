---
id: TASK-68b0b5cdd940
type: task
slug: veille-4-4-routes-api-veille-cran-veille-maquett
title: "Veille (4/4) : routes /api/veille, écran Veille (maquette), clips archivés masqués + Restaurer, Réglages › Veille avec clés masquées, SSE veille, CHANGELOG + GUIDE"
created: 2026-10-06T11:32:41Z
author: w-veille
status: open
scope:
  - clipper/web/**
  - tests/test_web*.py
  - CHANGELOG.md
  - docs/GUIDE.md
blocked_by: [TASK-3225a4f9df8c]
done_criteria: |
  Veille (4/4), SPEC veille R8, R9, R10 : API et écran « Veille » dans clipper/web (ADR-09ad : aucune logique réseau ni LLM dans le serveur web), clips archivés, Réglages › Veille, docs. Tests tests/test_web.py avec TestClient, state/ sous tmp_path, aucun réseau. Prouver : (1) GET /api/veille rend l'état du jour (sinon du dernier relevé) + selection + enabled + twitch_client_id_set/twitch_client_secret_set/youtube_api_key_set (booléens, jamais les valeurs) + next_run_at + running ; GET /api/veille/{date} 404 si absent ; les erreurs par source sont présentes telles quelles dans sources. (2) POST /api/veille/refresh → 202 et seulement state/veille/refresh.json écrit (test : aucun collecteur ni FakeBackend appelé par le processus web) ; 409 si running ou enabled false avec un message qui dit d'activer dans Réglages › Veille. (3) POST /api/veille/{date}/{candidate_id}/clip {channel, short_clips} → 202 avec l'entrée de file (clipper.veille.clip) ; 404 inconnu ; 409 déjà traité ; POST .../ignore → 200 ; POST /api/veille/clips/{video_id}/{clip_id}/restore → 200. (4) GET /api/clips masque les clips archived par selection/<date>.json sauf ?archived=1 ; chaque vue de clip porte veille: {date, status} ou null. (5) /api/settings : section veille présente ; GET ne contient jamais la valeur de twitch_client_secret ni youtube_api_key (test avec une valeur sentinelle), PUT avec ces clés les écrit dans config.toml, PUT sans elles les garde ; clipper.journal.mask_secrets masque ces clés. (6) SSE : un changement sous state/veille/ émet un événement kind "veille". (7) Page statique : entrée « Veille » dans la navigation (compteur = propositions proposed) et dans la barre basse mobile à la place de Vidéos, clipper/web/static/screens/veille.js qui suit la maquette research/maquettes/veille.html (sections : bandeau sources avec erreur visible, KPI, propositions avec raison + choix du style + Clipper/Ignorer, meilleurs clips du jour avec archivés repliés + Restaurer, tableau ce qui monte avec null expliqué, aperçu réglages) ; état vide « Veille désactivée » avec lien Réglages ; bouton Rafraîchir désactivé pendant running ; écran Clips : filtre « Archivés » ; Réglages : section Veille (goûts, nombres, heure, clés). (8) CHANGELOG.md [Non publié] et docs/GUIDE.md : section Veille (activation, création des clés Twitch et YouTube, Steam sans clé, coût, où sont les fichiers). pytest vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Contexte : ADR ADR-ca9a5792739c (proposé) et SPEC SPEC-bdd9e0db8905 (proposée), planifiés le 2026-10-06 ; maquette research/maquettes/veille.html (local). Lire d'abord clipper/watch.py (même forme de bibliothèque, listeur injecté) et tests/test_watch.py (fixture env). Style : reprendre clipper/web/static/style.css (classes existantes : panel, list-item, chip, kpi, reason, src-ico) et screens/watch.js pour les boutons ; les secrets suivent le traitement de [web] token dans app.py (_settings_without_token).
