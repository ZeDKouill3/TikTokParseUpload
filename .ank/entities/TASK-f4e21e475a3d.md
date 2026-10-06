---
id: TASK-f4e21e475a3d
type: task
slug: veille-jeux-steam-qui-montent-visibles-m-me-sans
title: "Veille : jeux Steam qui montent visibles même sans correspondance Twitch FR (nouveau dans le top, gain de places)"
created: 2026-10-06T14:06:14Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/veille.py
  - clipper/web/static/screens/veille.js
  - clipper/web/static/screens/veille.css
  - tests/test_veille.py
  - tests/test_web_veille.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Constat 2026-10-06 16:05, relevé réel : Steam OK (noms + rank/last_week_rank, ex. AION 2 rang 5, last_week_rank -1 = nouveau dans le top) mais day.games = [] car la liste des jeux (SPEC-bdd9 R4) part des jeux Twitch ; sans clé Twitch l'écran « ce qui monte » est vide. Extension de R4 demandée par l'utilisateur (sans changer le reste) : ajouter aussi à day.games les jeux Steam du relevé qui MONTENT sans être déjà présents via Twitch — « nouveau dans le top » (last_week_rank absent, 0 ou négatif) ou gain de places ≥ un seuil réglable dans CONFIG_DEFAULTS de veille (ex. steam_rank_gain_min = 5) — avec les champs Twitch à null et une marque explicite (ex. source = « steam », twitch_match = false, affiché « hors Twitch FR »), les champs de gain de rang (steam_rank, steam_last_week_rank, steam_rank_gain ou steam_new_in_top), jamais un chiffre inventé (ADR-ad2e) ; nombre plafonné (réglable, ex. steam_risers_max = 10), exclure les jeux non-jeux évidents seulement s'il existe une donnée officielle pour le faire (sinon les garder). Ces jeux sont aussi donnés à Claude comme contexte. Écran Veille, tableau « ce qui monte » : ces lignes s'affichent avec « Nouveau dans le top Steam » ou « +N places », et « hors Twitch FR ». Tests rouges avant (relevé avec Twitch en erreur et Steam ok -> jeux non vides), aucun réseau, FakeBackend. CHANGELOG [Non publié].
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/23348fbff47a@6388201
    tree: scope/c373824740e8
    criteria: 6c96583442d3
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---
