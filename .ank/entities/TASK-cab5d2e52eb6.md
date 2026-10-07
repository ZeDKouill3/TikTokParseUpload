---
id: TASK-cab5d2e52eb6
type: task
slug: veille-les-lectures-d-abonn-s-steam-memberslistx
title: "Veille : les lectures d'abonnés Steam (memberslistxml) ne doivent plus dépasser la limite de Steam (HTTP 429)"
created: 2026-10-07T12:07:08Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/veille_sources.py
  - clipper/veille.py
  - tests/test_veille_sources.py
  - tests/test_veille.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  (1) Constat réel du 07/10/2026 12:31 : source steam_followers en erreur « HTTP 429 sur https://steamcommunity.com/games/2827820/memberslistxml/?xml=1 » avec steam_followers_pause_s = 1.0 et steam_followers_lookups_max = 200, donc aucun abonné relevé. (2) Un HTTP 429 sur memberslistxml n'abandonne plus toute la source : le collecteur attend (délai croissant, plafonné, horloge et attente injectées, en tenant compte de l'en-tête Retry-After s'il existe), réessaie le même appid au plus un nombre réglable de fois, journalise chaque attente ; essais épuisés : les abonnés déjà lus sont gardés, les appids restants valent null et sont comptés dans counts.rate_limited, la source passe en statut partiel visible (jamais ok muet, ADR-ad2e), les autres sources continuent. (3) Défauts réglables dans CONFIG_DEFAULTS de veille : steam_followers_pause_s relevé (au moins 2.0) et steam_followers_lookups_max abaissé (au plus 60), avec bornes validées ; le calcul de l'ordre de priorité des appids de SPEC-df51 R21 est inchangé. (4) Tests sans réseau avec transport et attente injectés : 429 puis 200 au 2e essai, 429 persistant, Retry-After lu, plafond d'attente. (5) Cette tâche ne modifie pas SPEC-df51 : elle ne change que des défauts et la gestion du 429 permise par ADR-05a4 (plafond et pause par construction). Si elle croit devoir amender une règle de la SPEC, elle release au lieu de le faire. (6) CHANGELOG [Non publié]. (7) pytest complet vert.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/629f5b36cad5@2507c65
    tree: scope/983dd3863d69
    criteria: bf8c418a416b
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Relevé réel 07/10/2026 12:31, écran Veille : « Steam (abonnés) : erreur HTTP 429 ». ADR-05a4 autorise memberslistxml avec plafond et pause réglables.
