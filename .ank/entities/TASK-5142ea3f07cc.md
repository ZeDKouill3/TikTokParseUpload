---
id: TASK-5142ea3f07cc
type: task
slug: readme-captures-refaites-en-th-me-clair-vignette
title: "README : captures refaites en thème clair, vignettes et noms tiers floutés, nouveaux écrans (veille, fiche clip, rétention)"
created: 2026-10-09T11:59:54Z
author: nicoc@zedk_ordi
status: open
scope:
  - README.md
  - docs/assets/readme/**
  - tests/test_readme_assets.py
  - tests/test_docs_installation.py
  - tests/test_release_docs.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Demande de l'utilisateur (09/10) après TASK-fde2eb1e333a (README refondu sans nouvelles captures) : refaire les captures du README, THÈME CLAIR UNIQUEMENT. (1) Toutes les captures d'écran de la console citées par README.md sont refaites sur la console déjà lancée http://127.0.0.1:8000 (Chrome headless Playwright, channel chrome, timezone Europe/Paris, locale fr-FR, thème clair forcé), uniquement par des GET de pages et le défilement : ne JAMAIS cliquer un bouton qui écrit, ne jamais lancer un autre serve ni un worker. Ajouter les écrans nouveaux qui manquent au README s'ils montrent une fonction réelle : Veille, fiche clip (#/clip/<video_id>/<clip_id>), bloc « Rétention à maturité » de Statistiques. Format et taille comme les captures existantes (.webp, mêmes largeurs), noms <écran>-light.webp. (2) Le dépôt est PUBLIC : sur chaque capture, flouter fortement (flou gaussien ou pixelisation, illisible) toute vignette/jaquette/miniature de vidéo et tout nom ou pseudo de chaîne/streamer tiers et tout titre de VOD tiers ; aucune adresse e-mail, mot de passe, jeton, cookie ; ne pas capturer l'écran Comptes s'il montre des e-mails (sinon les flouter) ; jamais le nom de la chaîne Twitch amie (Madajel). Vérifier chaque image en la relisant avant de la garder. (3) README.md : chaque <picture> devient une simple <img> vers la version claire (plus de <source> sombre) ; les fichiers *-dark.webp qui ne sont plus cités sont supprimés ; les GIF animés existants restent tels quels s'ils ne montrent rien de sensible (sinon les retirer du README et le dire dans le commit). (4) tests/test_readme_assets.py et les autres tests des docs restent verts : adapter un test SEULEMENT s'il exige des variantes sombres, en le disant dans le commit. (5) Aucune modification de code de production. CHANGELOG [Non publié] Modifié (une ligne).
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
