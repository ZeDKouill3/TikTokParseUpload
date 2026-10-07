---
id: TASK-db2bffaee0d0
type: task
slug: veille-historique-3-3-cran-veille-sources-steam
title: "Veille historique (3/3) : écran Veille (sources « Steam (avis 30 j) » et « Twitch (VOD 30 j) », compteurs d'écartées par raison, courbe 30 j par jeu suivi, résumé sur les propositions, plus d'« Accès non vérifié »), /api/veille et réglages (dix clés R22, twitch_access_check_max ignorée), GUIDE, CHANGELOG (SPEC-85a0 R27)"
created: 2026-10-07T13:02:17Z
author: w-histplan
status: open
scope:
  - clipper/web/app.py
  - clipper/web/static/screens/veille.js
  - clipper/web/static/screens/settings.js
  - tests/test_web_veille.py
  - docs/GUIDE.md
  - CHANGELOG.md
blocked_by: [TASK-70228c3a3499]
done_criteria: |
  Tests verts sans réseau (tests/test_web_veille.py sur un état fabriqué sous tmp_path portant trend_30d, sources.steam_reviews, sources.twitch_vods_30d, excluded.access_restricted / access_unreachable), pytest complet vert. (1) GET /api/veille et /api/veille/{date} rendent trend_30d, les deux sources et excluded.access_* tels qu'écrits ; settings expose les dix clés de SPEC-85a0 R22 ; PUT /api/settings les écrit, refuse une valeur hors bornes (400 avec le message de VeilleError) et accepte un corps portant encore twitch_access_check_max (clé ignorée). (2) veille.js : SOURCE_LABELS « Steam (avis 30 j) » et « Twitch (VOD 30 j) », COUNT_LABELS rate_limited « non relevés (limite) » et unreachable « VOD injoignables écartées », KPI « n VOD écartées : réservées aux abonnés » et « n VOD écartées : injoignables après N essais » (N = twitch_access_attempts), colonne « 30 j » de « Ce qui monte » avec une mini-courbe SVG en ligne sans bibliothèque par jeu suivi (séries steam_reviews, twitch_vods_fr (vods), twitch_viewers_fr, couleurs distinctes, légende, jours sans mesure non reliés, « n j mesurés / 30 », « pic <date> », « jeu non suivi » sinon, « 1 jour de mesure » sous 2 points), carte de proposition avec la courbe de son jeu et le résumé « s4 → s1 » de steam_reviews ou à défaut twitch_vods_fr, plus aucune mention « Accès non vérifié » (le test existant qui l'exige est remplacé) ; aucun calcul de série dans le JS (lecture de summary et points seulement). (3) settings.js et l'aperçu des réglages de l'écran Veille montrent trend_days, trend_games_max, twitch_access_attempts, twitch_access_retry_pause_s, steam_reviews_pause_s, twitch_history_pages_max, les autres clés R22 dans « autres réglages ». (4) docs/GUIDE.md : section Veille complétée (origine de chaque courbe, endpoint non documenté et ce qui se passe s'il change, plafond Twitch 500 donc jours anciens inconnus, ce que Claude reçoit, test d'accès à N essais et écartées par raison, dix réglages, twitch_access_check_max ignorée) ; CHANGELOG [Non publié] : Ajouté (historique 30 j, deux sources, courbes, réglages), Modifié (test d'accès : écartées, plus de « non vérifié », clé retirée). (5) Aucun ADR ni SPEC amendé.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

Dépend des champs écrits par les tâches 1/3 et 2/3 (trend_30d, counts, excluded). Capture réelle de l'écran souhaitée dans le log de la tâche (état réel après un relevé), comme pour TASK-68b0.
