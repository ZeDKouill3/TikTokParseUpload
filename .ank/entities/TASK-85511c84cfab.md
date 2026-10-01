---
id: TASK-85511c84cfab
type: task
slug: maquette-cliquable-du-tableau-de-bord-statistiqu
title: Maquette cliquable du tableau de bord Statistiques TikTok (avant spec)
created: 2026-10-01T21:59:18Z
author: nicoc@zedk_ordi
status: open
scope:
  - docs/maquette-stats/**
blocked_by: []
done_criteria: |
  docs/maquette-stats/index.html autonome (aucun réseau, données factices plausibles, noms neutres : compte « ma_chaine », jamais de vrai nom), reprenant le style de docs/maquette-web-v2 (thème sombre orange, polices, composants ; réutiliser ses css/fonts par chemins relatifs ou copie) : (1) en haut, sélecteur de compte TikTok (et rappel de la chaîne liée) + période 7 / 28 / 60 jours + date du dernier relevé et bouton Relever maintenant ; (2) onglet Vue d'ensemble : 5 tuiles (vues de vidéo, vues du profil, likes, commentaires, partages) avec évolution en % vs période précédente, courbe par jour avec choix de la métrique ; (3) onglet Publications : tableau triable (vignette, légende, date, vues, likes, commentaires, partages, temps moyen, % vu en entier), clic -> panneau de détail du post (chiffres clés, courbe de rétention, sources de trafic ou « disponible dès 100 vues », lien TikTok, lien vers le clip et la vidéo source dans Clipper) ; (4) états vides et « en cours de traitement » montrés ; (5) mobile correct ; (6) tests existants verts.
criteria_by: creator
verify: [tests]
schema: 4
version: 1
---

L'utilisateur veut un écran Statistiques façon TikTok Studio, basé UNIQUEMENT sur le relevé des pages TikTok Studio (aucun import CSV, aucune mesure interne). Maquette à valider avant la spec.
Données disponibles (relevé réel, FR) : page Données analytiques du compte, période 7 / 28 / 60 jours : Vues de la vidéo, Vues du profil, J'aime, Commentaires, Partages (chacun avec évolution vs période précédente) ; Publications (/tiktokstudio/content) : par post légende, date, visibilité, Vues, J'aime, Commentaires ; analyse d'un post (/tiktokstudio/analytics/<id>) : Vues de vidéo, Temps de lecture total, Temps de visionnage moyen, A regardé toute la vidéo (%), Nouveaux followers, Taux de rétention (courbe), Sources de trafic (dès 100 vues) ; onglets Spectateurs (types, âge, sexe, lieux) et Engagement (likes dans le temps, mots les plus utilisés dans les commentaires). Les courbes par jour viennent de nos relevés horodatés successifs.
