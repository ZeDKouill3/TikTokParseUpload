---
id: TASK-974ead6bddc2
type: task
slug: alerte-0-vue-24-h-un-post-publi-qui-n-a-presque
title: "Alerte « 0 vue à 24 h » : un post publié qui n'a (presque) aucune vue 24 h après sa mise en ligne est signalé sur le tableau de bord et au journal"
created: 2026-10-08T13:06:32Z
author: nicoc@zedk_ordi
status: done
scope:
  - clipper/learning.py
  - clipper/web/app.py
  - clipper/web/static/screens/dashboard.js
  - tests/test_learning.py
  - tests/test_web.py
  - CHANGELOG.md
blocked_by: []
done_criteria: |
  Tests verts sans réseau, pytest complet vert. Besoin utilisateur (accord 06/10, confirmé 08/10) : repérer vite un post TikTok bloqué ou masqué, ou un compte qui ne diffuse plus (cas réel : anciens comptes ClipManiaq3/clippyqaniaque à 0 vue depuis le 03/10, vus trop tard). (1) À partir des relevés de stats TikTok déjà faits (state/stats/tiktok, entrées stats du journal des résultats ; aucun nouveau relevé, aucun scraping de plus), un post en ligne depuis au moins [learning] (ou section existante la plus proche) zero_view_alert_hours (CONFIG_DEFAULTS, défaut 24) dont le dernier relevé donne au plus zero_view_alert_max_views (défaut 0 ou petit, documenté) est en alerte. (2) Si plusieurs posts d'un même compte sont en alerte (zero_view_alert_account_min, défaut 2), l'alerte est au niveau du compte (« le compte ne diffuse peut-être plus »). (3) Alerte visible sur le tableau de bord (dashboard.js, via une route API) avec le post (compte, clip, date, vues, heure du relevé) et une ligne de journal WARNING une seule fois par post. (4) Un post sans relevé après 24 h n'est pas compté 0 : il est signalé « pas de relevé » à part, jamais une fausse alerte (ADR-ad2e). Un post « supprimé de la plateforme » (TASK-5a7b) ou d'un compte en pause est ignoré. (5) Tests sans réseau : post à 0 vue après 24 h -> alerte ; 0 vue à 10 h -> rien ; sans relevé -> « pas de relevé » ; 2 posts du même compte -> alerte compte ; supprimé/pause ignorés ; route + rendu du tableau de bord. CHANGELOG [Non publié] Ajouté.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/84f9d51e48dc@4b0f8fb
    tree: scope/8fe75f0e1398
    criteria: a530ba716c74
    verifier: tests@c7b454d16c90
    via: verifier
schema: 4
version: 3
---
