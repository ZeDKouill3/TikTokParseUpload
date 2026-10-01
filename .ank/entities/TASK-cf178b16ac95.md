---
id: TASK-cf178b16ac95
type: task
slug: comptes-comptes-de-publication-connexion-v-rifi
title: "Comptes = comptes de publication : connexion vérifiée, case prêt à publier, compte choisi par publication (SPEC-00d1)"
created: 2026-10-01T15:59:05Z
author: nicoc@zedk_ordi
status: in_progress
scope:
  - clipper/accounts.py
  - clipper/browser.py
  - clipper/publish.py
  - clipper/tiktok.py
  - clipper/worker.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_accounts.py
  - tests/test_browser.py
  - tests/test_publish.py
  - tests/test_tiktok.py
  - tests/test_worker.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Règles R1 à R6 de SPEC-00d1459bed03 tenues à la lettre, prouvées par tests ciblés sans navigateur réel ni réseau (lecture de cookies simulée) : (1) clipper.browser expose l'état de connexion TikTok d'un profil (jamais connecté / connecté avec date / session expirée) en lisant localement les cookies du profil, sans navigation ; (2) le compte porte ready_to_publish ; l'API refuse de le cocher sans connexion vérifiée (message explicite) ; décochage automatique journalisé quand la session expire ou après un arrêt R4 (captcha, vérification) ; (3) l'entrée de publication porte account (prérempli par [channel] tiktok_account, modifiable à la validation et à la programmation parmi les comptes prêts) ; le worker publie avec ce compte ; compte non prêt = entrée non tentée, en attente avec raison visible, jamais de repli vers un autre compte ; (4) écran Comptes : état de connexion, case prêt à publier (grisée avec raison), posts du jour / plafond, dernier échec avec capture, boutons Se connecter et Relever les stats ; le calendrier Publication et la validation d'un clip affichent et permettent de choisir le compte ; tests API + statique ; (5) tests existants verts. python -m pytest -q tests/test_accounts.py tests/test_browser.py tests/test_publish.py tests/test_tiktok.py tests/test_worker.py tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 5
---

Implémente SPEC-00d1459bed03 (ratifiée 2026-10-01).
