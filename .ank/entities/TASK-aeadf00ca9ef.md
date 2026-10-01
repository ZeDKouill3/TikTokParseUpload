---
id: TASK-aeadf00ca9ef
type: task
slug: statistiques-tableau-de-bord-tiktok-par-compte-v
title: "Statistiques : tableau de bord TikTok par compte (vue d'ensemble, liste des vidéos, fiche de stats par vidéo) (SPEC-86fe)"
created: 2026-10-01T22:24:23Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/tiktok.py
  - clipper/assets/tiktok_selectors.toml
  - clipper/worker.py
  - clipper/web/app.py
  - clipper/web/static/**
  - tests/test_tiktok.py
  - tests/test_worker.py
  - tests/test_web.py
blocked_by: [TASK-3a08291b21b7]
done_criteria: |
  Règles R1 à R6 de SPEC-86fea5620c7f tenues, prouvées par tests ciblés sans navigateur réel ni réseau (fausses pages) : (1) relevé du compte (page Données analytiques, 3 périodes), de la liste des posts et de chaque post (vue d'ensemble, viewers, engagement), valeurs absentes = null ; (2) historique horodaté ajouté sous state/stats/tiktok/<compte>/ sans jamais écraser ; courbes par jour et évolutions calculées depuis l'historique ; (3) écran Statistiques selon la maquette : sélecteur de compte, période, dernier relevé + Relever maintenant, onglet Vue d'ensemble (5 tuiles, courbe), onglet Vidéos (liste triable avec recherche), fiche d'une vidéo avec onglets Vue d'ensemble / Spectateurs / Engagement, liens TikTok, clip et vidéo source, mention « publié hors Clipper » ; compte non prêt = message, pas de relevé ; (4) import CSV retiré (route et interface) ; coûts LLM, durées d'étapes et vidéos par statut déplacés dans le Tableau de bord ; (5) relevé opportuniste : chaque fois que le robot est déjà sur une page TikTok Studio pour autre chose (publication terminée -> /tiktokstudio/content, vérification de connexion), il relève au passage ce que la page affiche (liste des posts et leurs vues/likes/commentaires) et l'ajoute à l'historique, sans navigation supplémentaire ni attente notable ; testé avec la fausse page ; (6) node --check des JS ; tests existants verts. python -m pytest -q tests/test_tiktok.py tests/test_worker.py tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

Implémente SPEC-86fea5620c7f (ratifiée 2026-10-01). Maquette validée : docs/maquette-stats/index.html (reprendre sa mise en page dans la vraie console). Repères réels déjà relevés (FR) : page Données analytiques du compte https://www.tiktok.com/tiktokstudio/analytics : bouton période « 7 derniers jours », tuiles en boutons « Vues de la vidéo -- 0 (--) », « Vues du profil », « J'aime », « Commentaires », « Partages » (valeur puis évolution entre parenthèses) ; Publications /tiktokstudio/content : tableau « Contenu (Créé le) | Politique de confidentialité | Vues | J'aime | Commentaires | Actions », lien du post a[href*='/video/'] (/@<compte>/video/<id>, texte = légende) ; analyse d'un post /tiktokstudio/analytics/<id>?qa_enter_from=analytics : cartes [data-tt='VideoOverviewPage_VideoMetricsCard_FlexItem'] « libellé | valeur » (Vues de vidéo, Temps de lecture total 0h:00m:00s, Temps de visionnage moyen 0s, A regardé toute la vidéo 0%, Nouveaux followers) ; onglets /viewers (Total des spectateurs, Types : récurrents/nouveaux, followers/non followers, Âge, Sexe, Lieux) et /engagement (J'aime dans le temps, Mots les plus utilisés dans les commentaires) ; « en cours de traitement » ou « dès 100 vues » = null. Le relevé existant (fetch_stats, SPEC-9225 R7) est à étendre, pas à doubler.
