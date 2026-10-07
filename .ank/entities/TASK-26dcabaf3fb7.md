---
id: TASK-26dcabaf3fb7
type: task
slug: download-r-essayer-vite-la-r-cup-ration-twitch-c
title: "Download : réessayer vite la récupération Twitch coupée par le réseau (WinError 10054 sur usher) avant d'échouer"
created: 2026-10-07T07:12:34Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/download.py
  - tests/test_download.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts, sans réseau (yt-dlp simulé) : quand le téléchargement échoue sur une erreur de transport réseau (connexion fermée par l'hôte distant / WinError 10054 / connection reset, y compris « Failed to download m3u8 information »), l'étape download réessaie aussitôt jusqu'à [download] network_retries fois (nouveau réglage CONFIG_DEFAULTS, défaut 15) avec une pause [download] network_retry_pause_s (défaut 5) entre deux essais, chaque essai journalisé (INFO, numéro/total, raison courte) ; un succès en cours de route termine l'étape normalement ; essais épuisés : l'erreur d'origine remonte telle quelle (le pipeline garde son mécanisme d'échec transitoire et de reprise différée inchangé). Aucune autre erreur n'est réessayée ici : contenu réservé aux abonnés, vidéo privée/supprimée, erreur de format remontent au premier essai. Pause injectable dans les tests (pas d'attente réelle). Entrée CHANGELOG [Non publié].
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

Enquête réseau 2026-10-07 (research/twitch-block.md) : coupures TLS intermittentes vers usher.ttvnw.net seulement (CloudFront Twitch), 1/6 à 24/24 de réussite selon l'heure ; gql/api/static-cdn OK ; yt-dlp à jour ; Chrome passe en réessayant. Solution retenue par l'utilisateur : réessais rapprochés dans l'étape download.
