---
id: ADR-1cf0b17d48b3
type: adr
slug: apprentissage-du-jury-partir-des-erreurs-sans-un
title: Apprentissage du jury à partir des erreurs, sans uniformisation
created: 2026-09-25T18:38:15Z
author: nicoc@zedk_ordi
status: accepted
scope:
  - clipper/**
constraint: |
  Le jury n'apprend que de signaux réels (qa, décisions humaines, statistiques de plateforme), jamais de l'accord entre juges. L'ajustement automatique porte sur des poids de juges bornés (défaut 0,5 à 1,5), calculés sur un minimum de clips ; toute retouche de prompt est proposée par lot, versionnée, et adoptée seulement si elle fait mieux en rejeu sur des candidats passés au résultat connu, sans rapprocher deux perspectives. Une part d'exploration configurée est réservée aux candidats incertains. Le juge conformité et son veto ne sont jamais recalibrés sur l'audience.
ratified: e82137d83ec7
verified:
  - by: nicoc@zedk_ordi
    at: 2026-09-25T18:41:54Z
schema: 4
version: 2
---

## Contexte
Le jury (ADR-ff87) remplace l'humain en mode auto. L'utilisateur veut que les erreurs des juges servent aux décisions suivantes, sans que le jury s'uniformise ni se dégrade. Risques identifiés : prendre le consensus pour la vérité (les juges convergent, le jury perd son intérêt), biais de sélection (on ne connaît le résultat que des clips publiés), bruit des statistiques de plateforme, prompts qui gonflent et se contredisent, optimisation des vues au détriment de la qualité (clickbait), et un veto conformité qu'on finirait par désapprendre.

## Décision
1. **Vérité terrain = signaux réels uniquement**, jamais l'accord avec les autres juges : rejets et défauts relevés par qa, décisions humaines (mode review, échantillon), et, dès que la publication existera, statistiques de la plateforme (rétention à 3 s, visionnage complet, partages). Ces résultats sont journalisés par clip (journal des résultats), reliés à la trace du jury.
2. **Calibration par poids** : à intervalle configuré, on mesure pour chaque juge à quel point ses notes prédisaient les résultats réels, et on ajuste son poids dans l'agrégation, borné (défaut 0,5 à 1,5), sur un nombre minimal de clips, avec lissage. Automatique, transparent, réversible ; les prompts ne changent pas.
3. **Retouches de prompts par lots, jamais au fil de l'eau** : un « coach » analyse périodiquement les erreurs et PROPOSE des retouches ; une retouche n'est adoptée que si, rejouée sur des candidats passés dont le résultat est connu, elle fait mieux que la version en place ; chaque prompt est versionné ; le nombre de leçons par juge est plafonné ; une retouche qui rapproche deux perspectives est refusée.
4. **Exploration** : une petite part des clips (défaut 10 %) est choisie parmi les candidats où le jury hésite, pour apprendre ce qu'il sous-estime ; ces clips sont marqués comme exploration.
5. **Conformité hors apprentissage** : le juge conformité et son veto ne sont jamais recalibrés à partir des statistiques d'audience.

## Conséquences
- Tant que la publication n'existe pas, la boucle ne se nourrit que de qa et des revues humaines ; elle se renforce ensuite.
- Tout ajustement est traçable (poids datés, prompts versionnés, rejeu comparatif).
