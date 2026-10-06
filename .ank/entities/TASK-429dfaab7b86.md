---
id: TASK-429dfaab7b86
type: task
slug: stats-tiktok-confirmer-sur-la-vraie-page-les-rep
title: "Stats TikTok : confirmer sur la vraie page les repères des onglets Spectateurs/Engagement et de la rétention (viewers_card introuvable, relevé arrêté)"
created: 2026-10-06T13:28:58Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/assets/tiktok_selectors.toml
  - clipper/tiktok.py
  - tests/test_tiktok.py
  - tests/fixtures/tiktok/**
blocked_by: []
done_criteria: |
  Défaut constaté 2026-10-06 15:26 : relevé complet du compte 1ad53325b65d (ClipperFou) arrêté par « élément attendu absent après 30 s : viewers_card » (state/stats/tiktok/1ad53325b65d/20261006T132330042815Z.error.json, capture state/browser/1ad53325b65d/captures/20261006T132330-element_missing.png : la page Spectateurs s'affiche normalement, cartes Total des spectateurs, Types de spectateurs, Sexe, Âge, Lieux). Cause : les repères viewers_card, engagement_card et retention_point de clipper/assets/tiktok_selectors.toml n'ont JAMAIS été confirmés sur la vraie page (commentaire « A VERIFIER SUR LA VRAIE PAGE »). Méthode ank-diagnose : relever en LECTURE SEULE le DOM réel des onglets Spectateurs et Engagement de Données analytiques d'un post et de la courbe de rétention (outils existants research/tiktok-inspect/dump_cdp.py / inspect_studio.py, Chrome du profil state/browser/1ad53325b65d ; AUCUNE publication, aucun clic qui modifie quoi que ce soit ; fermer le Chrome après ; le garde réseau [network] block_browser bloque le navigateur Clipper sur IP UK : l'inspection passe par les outils research/, ne modifie pas config.toml) ; copier un extrait HTML minimal anonymisé (< 100 Ko) en fixture sous tests/fixtures/tiktok/. Corriger les 3 repères (data-tt réels ou libellés stables), retirer la mention « A VERIFIER » de ceux confirmés ; tests de lecture des cartes sur la fixture (rouges avant), aucun réseau dans les tests. Les règles existantes restent : valeur introuvable = null ou arrêt explicite, jamais devinée (ADR-ad2e) ; onglet « dès 100 vues » = null.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---
