---
id: SPEC-86fea5620c7f
type: spec
slug: statistiques-tableau-de-bord-tiktok-par-compte-u
title: "Statistiques : tableau de bord TikTok par compte, uniquement à partir du relevé de TikTok Studio"
created: 2026-10-01T22:23:45Z
author: nicoc@zedk_ordi
status: superseded
scope:
  - clipper/tiktok.py
  - clipper/assets/tiktok_selectors.toml
  - clipper/worker.py
  - clipper/web/**
references: [SPEC-922573c1e68f, SPEC-e500759ebe68, ADR-1a581b7e721e, ADR-ad2e562b1810, SPEC-c1001cb7cbdb]
ratified: b3281634f49c
verified:
  - by: nicoc@zedk_ordi
    at: 2026-10-01T22:24:08Z
schema: 4
version: 3
---

## Objet
L'écran Statistiques devient un tableau de bord à la TikTok Studio, par compte, alimenté UNIQUEMENT par le relevé des pages de TikTok Studio. Maquette validée par l'utilisateur : docs/maquette-stats/index.html (2026-10-01), avec en plus la liste des vidéos et leurs stats individuelles.

## Règles
R1. Source unique. Toutes les valeurs affichées viennent du relevé de TikTok Studio : page Données analytiques du compte (périodes 7 / 28 / 60 jours : vues de la vidéo, vues du profil, likes, commentaires, partages, avec l'évolution donnée par TikTok), page Publications (/tiktokstudio/content : par post légende, date, visibilité, vues, likes, commentaires) et analyse de chaque post (/tiktokstudio/analytics/<id> et ses onglets viewers et engagement). L'import CSV est retiré. Les mesures internes (coûts LLM, durées d'étapes, vidéos par statut) quittent cet écran et vont dans le Tableau de bord.
R2. Historique. Chaque relevé est conservé horodaté (ajout, jamais d'écrasement) sous state/stats/tiktok/<compte>/ ; les courbes par jour sont calculées à partir de cet historique. Une valeur que TikTok n'affiche pas encore (en cours de traitement, moins de 100 vues) est null explicite, jamais 0 inventé.
R3. Écran. En haut : sélecteur de compte TikTok (rappel de la chaîne liée), période 7 / 28 / 60 jours, date du dernier relevé et bouton « Relever maintenant ». Onglet « Vue d'ensemble » : 5 tuiles avec évolution en %, courbe par jour avec choix de la métrique. Onglet « Vidéos » : la liste de toutes les vidéos publiées du compte, comme TikTok Studio : vignette verticale, légende, date, visibilité, vues, likes, commentaires, partages, temps de visionnage moyen, part vue en entier ; tri par colonne et recherche. Clic sur une vidéo : sa fiche de stats avec les onglets de TikTok (Vue d'ensemble : chiffres clés et courbe de rétention ; Spectateurs : types, âge, sexe, lieux ; Engagement : likes dans le temps, mots les plus utilisés dans les commentaires), le lien TikTok, et les liens vers le clip et la vidéo source dans Clipper quand le post vient de Clipper.
R4. Relevé. À la demande (bouton) et périodique par le worker ([tiktok] stats_interval_h) ; un compte non prêt à publier (SPEC-e500) n'est pas relevé et l'écran le dit ; arrêt sûr R4 de SPEC-9225 (captcha, page inattendue) ; repères dans tiktok_selectors.toml. Les posts publiés hors de Clipper apparaissent aussi (la liste vient de TikTok).
R5. Liens Clipper. Un post est relié à son clip par l'id ou l'URL enregistrés à la publication ; un post sans lien Clipper est affiché comme « publié hors Clipper ».
R6. Tests sans navigateur ni réseau : fausses pages pour chaque relevé, historique ajouté et jamais écrasé, null explicites, calcul des courbes et des évolutions, liste et tri des vidéos, fiche d'une vidéo, compte non prêt, liens clip/post, absence de l'import CSV.
