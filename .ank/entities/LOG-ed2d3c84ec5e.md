---
id: LOG-ed2d3c84ec5e
type: log
title: "geo_url = https://ipinfo.io/json : HTTPS, sans clé, 1 requête réelle vérifiée -> {ip, city, country"
created: 2026-10-05T19:30:56Z
author: w-30cceb3a2e90
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
about: TASK-30cceb3a2e90
seq: 2
schema: 4
version: 1
---

 (ISO2), org (AS + FAI), ...}; pas de country_name : table locale des pays courants, sinon le code. Garde navigateur : network.require_expected_country appelée dans browser._open_context; fetcher injectable (use_fetcher) pour les tests.
