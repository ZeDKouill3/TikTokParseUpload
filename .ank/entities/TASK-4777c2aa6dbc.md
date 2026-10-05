---
id: TASK-4777c2aa6dbc
type: task
slug: stats-tiktok-rep-rer-les-vid-os-restreintes-pas
title: "Stats TikTok : repérer les vidéos restreintes (« pas éligible au fil Pour toi ») pendant le relevé et les montrer"
created: 2026-10-05T18:04:51Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/tiktok.py
  - clipper/assets/tiktok_selectors.toml
  - clipper/web/static/screens/stats.js
  - tests/test_tiktok.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Tests verts, sans réseau, node --check sur stats.js : relevé réel 2026-10-04 (research/tiktok-inspect/constats-strikes.md, strikes1.png) : la page /tiktokstudio/analytics/<id>/overview d'une vidéo restreinte affiche en haut le bandeau « Cette vidéo n'est pas éligible à la recommandation dans le fil d'actualité Pour toi. Si tu n'es pas d'accord avec cette restriction de contenu, tu peux envoyer une contestation. » (classes générées : repérer par le TEXTE). (1) Le relevé détaillé de chaque post lit ce bandeau : champ fyf_eligible (true si absent, false si présent) + fyf_notice (texte du bandeau) dans les stats du post ; repère par texte dans tiktok_selectors.toml, FR et EN (« not eligible for recommendation ») ; un post programmé non encore en ligne : fyf_eligible = null. (2) Écran Statistiques : pastille « Restreinte : pas dans Pour toi » sur chaque post concerné et, par compte, « N vidéos restreintes sur M en ligne ». (3) Tests avec la fausse page : bandeau présent, absent, post futur. Aucune valeur inventée (ADR-ad2e) : page de stats illisible = erreur explicite comme aujourd'hui.
criteria_by: creator
verify: [tests]
proof:
  - type: test
    ref: local/73618b7ef448@0942b6c
    tree: scope/9f97faddffd2
    criteria: 03d92b869856
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 3
---

Demande utilisateur 2026-10-04/05 : 0 vue sur ses deux comptes TikTok ; une vidéo porte le bandeau d'inéligibilité au fil Pour toi (contenu non original, règles FYF de TikTok). Il veut voir d'un coup ce qui passe et ce qui est bloqué.
