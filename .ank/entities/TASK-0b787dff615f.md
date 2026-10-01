---
id: TASK-0b787dff615f
type: task
slug: tiktok-publication-imm-diate-ou-programm-e-par-l
title: "TikTok : publication immédiate ou programmée par le worker, arrêt sûr, plafonds (SPEC-9225 R3-R6, R9)"
created: 2026-10-01T14:19:57Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/tiktok.py
  - clipper/assets/tiktok_selectors.toml
  - clipper/publish.py
  - clipper/worker.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_tiktok.py
  - tests/test_publish.py
  - tests/test_worker.py
  - tests/test_web.py
  - tests/integration/test_tiktok_real.py
blocked_by: [TASK-e522cbcde0a9]
done_criteria: |
  Règles R3, R4, R5, R6 et R9 de SPEC-922573c1e68f tenues, prouvées par tests ciblés avec une fausse page Playwright (aucun navigateur réel, aucun réseau) : (1) clipper/tiktok.py, backend browser derrière une interface publish/fetch_stats choisie par [tiktok] backend (défaut browser ; api = erreur explicite « pas encore disponible ») ; (2) publication des modes immédiat et programmé (date du créneau, refus explicite au-delà de [tiktok] schedule_max_days) avec mp4 + légende + hashtags du sidecar ; succès = mark_published avec URL/id du post dans l'entrée et le sidecar ; (3) le worker prend les entrées dues de state/publish/<chaine>.json une à la fois, un compte à la fois ; chaîne sans tiktok_account = échec explicite ; (4) R4 : captcha, vérification, connexion expirée, élément absent après délai, page inattendue -> arrêt, entrée failed réessayable avec raison, capture d'écran sous state/browser/<compte>/captures/, événement vers la console ; jamais de résolution de captcha ; un test par cas ; (5) R5 : tous les sélecteurs et URL dans clipper/assets/tiktok_selectors.toml (test : aucun sélecteur en dur dans tiktok.py) ; (6) R6 : délais aléatoires bornés, max_posts_per_day et min_gap_minutes par compte, dépassement = report au prochain créneau libre journalisé ; (7) console : statut de chaque publication (en attente, programmée sur TikTok, publiée avec lien, échec avec capture et bouton Réessayer) ; (8) test réel optionnel tests/integration/test_tiktok_real.py (skipif sans CLIPPER_TIKTOK_REAL=1) qui publie en privé sur un compte de test ; (9) défauts de [tiktok] fixés par l'étude docs/tiktok-cadence.md §3.1, compte neuf : max_posts_per_day = 1, min_gap_minutes = 480, min_action_delay_s = 3, max_action_delay_s = 12, schedule_max_days = 10 ; le README donne les valeurs d'un compte établi (3, 240, 2, 8) ; (10) tests existants verts. python -m pytest -q tests/test_tiktok.py tests/test_publish.py tests/test_worker.py tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/c54c7dea7129@9742d9c
    tree: scope/44667b04e1ae
    criteria: b69adb2c843d
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 4
---

Deuxième tâche de SPEC-922573c1e68f : publication. S'appuie sur clipper.browser (TASK-e522).
