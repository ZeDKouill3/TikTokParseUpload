---
id: TASK-83ba75e3be47
type: task
slug: stats-tiktok-relev-seulement-l-usage-ouverture-s
title: "stats TikTok : relevé seulement à l'usage (ouverture si périmé, verrou par compte), worker coupé par défaut, liste complète des posts (SPEC-47e2)"
created: 2026-10-02T20:23:25Z
author: nicoc@zedk_ordi
status: in_progress
scope:
  - clipper/tiktok.py
  - clipper/worker.py
  - clipper/web/**
  - clipper/assets/tiktok_selectors.toml
  - config.example.toml
  - tests/**
blocked_by: []
done_criteria: |
  Tests unitaires (fausses pages, sans navigateur ni réseau) : ouverture de Statistiques avec relevé périmé -> relevé lancé, frais -> aucun ; deux demandes simultanées -> un seul relevé ; stats_interval_h = 0 -> le worker ne relève jamais, > 0 -> comportement actuel ; stats_interval_h < 0 -> erreur ; défilement : fausse liste en 3 lots (20+20+15) -> 55 posts lus, limite atteinte -> erreur journalisée ; publication relève toujours au passage. node --check sur chaque JS modifié.
criteria_by: creator
verify: [tests]
schema: 4
version: 2
---

Implémenter SPEC-47e2 (remplace SPEC-86fe ; lire `ank show SPEC-47e2`). Ce qui change par rapport au code actuel :
- `clipper/tiktok.py` CONFIG_DEFAULTS : `stats_interval_h` défaut 0 = coupé (aujourd'hui 24, et la validation l. ~135 refuse 0 : accepter 0, refuser < 0) ; nouvelle clé `stats_stale_min` (défaut 60, 0 = jamais à l'ouverture). Mettre à jour config.example.toml.
- `clipper/worker.py` `_stats_due` (~l. 401) : ne relève rien si stats_interval_h = 0.
- Web : à l'ouverture de l'écran Statistiques (`clipper/web/static/screens/stats.js` + endpoint dans `clipper/web/app.py`), si le dernier relevé du compte affiché a plus de stats_stale_min minutes, lancer un relevé en tâche de fond ; afficher tout de suite le dernier relevé connu + « relevé en cours », rafraîchir à la fin. Un seul relevé à la fois par compte (verrou côté serveur ; une 2e demande pendant un relevé renvoie l'état en cours, ne relance rien) — bouton « Relever maintenant » inclus.
- Relevé au passage pendant une publication : existe déjà, ne pas casser.
- Page Publications de TikTok Studio (/tiktokstudio/content) : faire défiler la liste (ou suivre la pagination) jusqu'à ce qu'aucun nouveau post n'apparaisse, avec limite de sécurité explicite (réglage, erreur journalisée si atteinte). Les repères vivent dans `clipper/assets/tiktok_selectors.toml` ; ne pas inventer de sélecteur non vérifié : réutiliser ceux de la liste existante et défiler le conteneur de la liste / la fenêtre (le sélecteur exact du conteneur sera vérifié en réel après merge).
