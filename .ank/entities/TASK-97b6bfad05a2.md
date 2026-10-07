---
id: TASK-97b6bfad05a2
type: task
slug: veille-historique-1-3-sources-steam-reviews-hist
title: "Veille historique (2/5) : sources steam_reviews (histogramme des avis, endpoint non documenté lu strictement) et twitch_vods_30d (Get Videos sur un mois, pages bornées, 429), twitch_id des jeux, jeux suivis, séries 30 j à trous (sources + historique propre), résumé par semaine, lignes tendance_30j du prompt (SPEC-85a0 R22-R25, R27 prompt)"
created: 2026-10-07T13:02:16Z
author: w-histplan
status: done
scope:
  - clipper/veille.py
  - clipper/veille_sources.py
  - tests/test_veille.py
  - tests/test_veille_sources.py
blocked_by: [TASK-a4bf52c1fbff]
done_criteria: |
  Tests verts sans réseau (transport, collecteurs, horloge et attente injectés), pytest complet vert. (1) CONFIG_DEFAULTS de clipper/veille.py gagne trend_days=30, trend_games_max=40, steam_reviews_pause_s=2.0, steam_reviews_retry_max=3, steam_reviews_retry_wait_max_s=60.0, twitch_history_pages_max=5, twitch_history_retry_max=2, twitch_history_retry_wait_max_s=60.0, bornes de SPEC-85a0 R22 validées (VeilleError nommant la clé ; history_days < trend_days nomme les deux clés). (2) Collecteur steam_reviews (veille_sources, R24) : URL et paramètres exacts de l'histogramme, User-Agent Clipper, un appel par appid séquentiel avec pause, lecture stricte de success et results.recent[] (toute autre forme -> SourceError contenant « format inattendu (endpoint non documenté) »), recent vide -> série ok sans point, jour en [veille] timezone, 429 avec attente croissante / Retry-After / plafond et réessais bornés puis rate_limited et statut partial ; rien d'autre lu. (3) Le collecteur twitch rend twitch_id par jeu, posé sur les jeux et dans history/<date>.json ; collecteur twitch_vods_30d (R25) : paramètres exacts de Get Videos (game_id, language, period=month, type=archive, sort=time, first=100), pagination par curseur plafonnée, agrégation vods/views par jour local, since = plus ancienne vidéo quand un curseur reste sinon premier jour de la fenêtre avec jours sans VOD à 0, champ absent -> SourceError, 429 attendu jusqu'à Ratelimit-Reset (borné) puis réessais bornés puis unavailable + partial, non appelé si la source twitch est en erreur. (4) collect (R23) : jeux suivis = community.ok ET au moins une candidate après le filtre de communauté (fixés avant le test d'accès, R23), ordre de games, plafond trend_games_max (0 -> sources skipped, au-delà compté skipped), trend_30d null sur un jeu non suivi, six séries nommées avec status/reason/since/points (jour sans mesure absent, jamais zéro ni interpolé ; séries propres relues de fichiers d'historique fabriqués avec trous), summary exact (bornes des semaines J-27..J0, moyenne arrondie, semaine vide null, peak, last, last_vs_peak_pct, s1_vs_s2_pct null si s2 manque ou vaut 0, measured_days, window_days) ; sources.steam_reviews et sources.twitch_vods_30d avec counts requested/found/unknown/skipped/rate_limited. (5) Prompt (R27) : en-tête tendance_30j et consigne ajoutés, une ligne par série sous chaque jeu suivi, forme exacte « tendance_30j <nom> : semaines=[s4, s3, s2, s1] pic=<date> (<v>) dernier=<date> (<v>) dernier_vs_pic=<n>% s1_vs_s2=<n>% jours_mesurés=<m>/<n> » (? pour une semaine null, inconnu pour pic/dernier/pourcentage null, depuis=<since> (plafond Twitch 500 VOD) quand since est postérieur au début de la fenêtre, vod_twitch_fr_par_jour écrit <vods> VOD (<views> vues)), « indisponible (<reason>) » pour une série unavailable, aucune ligne pour un jeu non suivi. (6) Aucune règle par jeu, aucun chiffre estimé : un test vérifie qu'un jour absent de toutes les sources est absent des points et qu'aucune semaine sans mesure ne vaut 0. Cette tâche ne touche ni clipper/web ni les docs, ne modifie pas le test d'accès Twitch (tâche 3/5), et n'amende aucune ADR ni SPEC.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/7a4d2107e663@23fc6da
    tree: scope/a011fbc18ad2
    criteria: 714bbde94d6f
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 6
---

Brief : research/cloud/veille-historique-plan.txt (local). Au 07/10/2026 : 23 jeux ont communauté ok et au moins une candidate, 4 d'entre eux un appid Steam ; 166/186 candidates « accès non vérifié ». Sources vérifiées à la main le 07/10/2026 (ADR-6e21). Ordre de collect : sources -> candidats -> communauté -> test d'accès (règle actuelle tant que 2/3 n'est pas faite) -> jeux suivis -> steam_reviews / twitch_vods_30d -> trend_30d -> prompt. Réutiliser le motif 429 de _steam_followers_collector (RateLimited, _retry_after_s) ; le transport rend un 3-uplet avec les en-têtes sur 429 : ajouter Ratelimit-Reset à côté de Retry-After.
