---
id: TASK-e522cbcde0a9
type: task
slug: navigateur-profils-par-compte-connexion-manuelle
title: "Navigateur : profils par compte, connexion manuelle, export des cookies YouTube, installation pour tout utilisateur du dépôt (SPEC-9225 R1, R2, R8)"
created: 2026-10-01T14:19:44Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/browser.py
  - clipper/channel.py
  - clipper/download.py
  - clipper/__main__.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tools/setup.ps1
  - README.md
  - pyproject.toml
  - tests/test_browser.py
  - tests/test_channel.py
  - tests/test_download.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Règles R1, R2 et R8 de SPEC-922573c1e68f tenues, prouvées par tests ciblés sans navigateur réel ni réseau (Playwright simulé) : (1) clipper/browser.py : chemin de profil state/browser/<compte>/ (id de compte validé, pas de traversée de chemin), ouverture visible d'un contexte persistant Playwright sur le vrai Chrome (channel chrome) ; Chrome ou Playwright absent = erreur explicite en français avec la commande d'installation, aucun repli ; aucune fonction ne saisit d'identifiant ; test que .gitignore couvre state/browser/ ; (2) commande « clipper browser login <compte> [--url URL] » qui ouvre le profil sur la page de connexion (TikTok par défaut, YouTube possible) et attend la fermeture de la fenêtre ; test du parseur et de l'appel ; (3) [channel] tiktok_account dans CONFIG_DEFAULTS de channel (défaut vide), validé contre les comptes de clipper.accounts quand il est réglé ; (4) R8 : export des cookies d'un profil vers un fichier cookies.txt au format Netscape (state/browser/<compte>/cookies.txt) ; [download] cookies_profile (défaut vide) : quand il est réglé, le téléchargement exporte les cookies de ce profil et passe le fichier à yt-dlp, prioritaire sur cookies_from_browser ; tests du format et de la priorité ; (5) console : dans l'écran Comptes, un compte a un bouton « Se connecter dans le navigateur » (route locale seulement, mêmes protections R3 que SPEC-6fa4) et l'état du profil (absent / présent, date) ; dans le formulaire de chaîne, choix du compte TikTok relié ; tests API + statique ; (6) installation : tools/setup.ps1 installe la dépendance playwright (pyproject) et vérifie la présence de Chrome (message clair sinon) ; README : section « Publier sur TikTok » (relier un compte, se connecter une fois, risques, captcha = arrêt) et « Cookies YouTube » ; tests README existants verts ; (7) tests existants verts. python -m pytest -q tests/test_browser.py tests/test_channel.py tests/test_download.py tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Première tâche de SPEC-922573c1e68f (ADR-1a581b7e721e) : socle navigateur. L'utilisateur exige que ça marche pour quelqu'un qui télécharge le dépôt (installation et doc).
