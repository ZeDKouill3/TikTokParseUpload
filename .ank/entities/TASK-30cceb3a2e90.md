---
id: TASK-30cceb3a2e90
type: task
slug: pays-de-l-ip-publique-affich-en-haut-droite-de-l
title: Pays de l'IP publique affiché en haut à droite de la console, alerte si ce n'est pas le pays attendu (réglage, France par défaut), pilotage du navigateur refusé hors pays
created: 2026-10-05T19:27:23Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/network.py
  - clipper/browser.py
  - clipper/web/app.py
  - clipper/web/static/index.html
  - clipper/web/static/app.js
  - clipper/web/static/style.css
  - clipper/web/static/screens/settings.js
  - tests/test_network.py
  - tests/test_browser.py
  - tests/test_web.py
  - config.example.toml
  - clipper/assets/config.example.toml
blocked_by: []
done_criteria: |
  Tests verts, sans réseau (service de géolocalisation simulé), node --check sur les JS modifiés : (1) nouveau module clipper/network.py avec CONFIG_DEFAULTS [network] : expected_country = "FR" (code ISO), geo_url (service HTTPS gratuit sans clé qui rend le pays de l'IP publique, ex. ipinfo.io/json ou équivalent, choisi et justifié dans ank log), cache_s = 60, block_browser = true ; fonction qui rend {ip, country, country_name, city, isp, ok (country == expected), checked_at} ; service injoignable = statut « inconnu » explicite, jamais « ok » par défaut (ADR-ad2e). (2) API GET /api/network : ce statut (cache respecté). (3) Console : en haut à droite de la barre du haut, une pastille avec le drapeau ou le code pays et la ville ; verte si pays attendu, rouge « IP hors France (UK) : ne publie pas » sinon, grise « pays inconnu » si le service ne répond pas ; rafraîchie toutes les 60 s et au retour sur l'onglet ; infobulle avec IP, FAI, ville. (4) Écran Réglages : choix du pays attendu (liste de pays courants + code libre), écrit dans config.toml [network] expected_country. (5) clipper.browser : avant d'ouvrir le navigateur piloté (publication et relevé de stats, TikTok et YouTube), si block_browser et pays != attendu ou inconnu : refus explicite « IP en <pays> (attendu <pays>) : passe sur le partage de connexion du téléphone » (le message remonte comme les autres arrêts de publication) ; tests. (6) config.example.toml documente la table [network].
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/597c493f0827@26a41d5
    tree: scope/09c53330ca76
    criteria: 429314e0a71e
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Demande utilisateur 2026-10-05 : « en haut à droite, un truc qui affiche la localisation du pays de l'IP, et prévient si ce n'est pas la France ou le pays choisi dans les paramètres ». Contexte : deux comptes TikTok créés et publiés depuis une IP UK n'ont fait aucune vue ; l'ancien compte, publié depuis la France, en faisait. L'utilisateur publie désormais via le partage de connexion de son téléphone (SIM française).
