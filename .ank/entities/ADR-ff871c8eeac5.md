---
id: ADR-ff871c8eeac5
type: adr
slug: jury-de-juges-ia-pour-les-d-cisions-de-jugement
title: Jury de juges IA pour les décisions de jugement du mode auto
created: 2026-09-25T18:31:29Z
author: nicoc@zedk_ordi
status: accepted
scope:
  - clipper/**
constraint: |
  En mode auto, une décision de jugement qui remplace l'humain (d'abord la sélection des moments) passe par clipper.jury : au moins 3 juges indépendants aux perspectives et prompts distincts notent à l'aveugle sur la grille, candidats anonymisés et mélangés ; un tour de débat ciblé sur les seuls désaccords ; agrégation par médiane, déterministe ; veto motivé du juge conformité ; notes, arguments, révisions et dissidences journalisés dans le JSON de l'étape. Une réponse de juge invalide est un échec (ADR-ad2e), sauf quorum explicitement configuré. La composition du jury est un réglage de config.
ratified: 2cab51e6639b
verified:
  - by: nicoc@zedk_ordi
    at: 2026-09-25T18:41:49Z
schema: 4
version: 2
---

## Contexte
La production doit tourner en mode auto, à la chaîne, sans humain (demande utilisateur 2026-09-25). Aujourd'hui une décision de jugement (quels moments garder) repose sur un seul appel LLM : essai réel sZi-qJ-5ptA, deux appels sur la même vidéo ont donné deux sélections différentes (9 puis 11 moments, autres bornes). Un seul juge est bruité et sans contre-pouvoir. Le mode review reste disponible (réglage `mode`), mais ne doit plus être nécessaire.

## Décision
Les décisions de jugement du mode auto passent par un **jury** (bibliothèque `clipper.jury`, utilisée par les étapes ; ce n'est pas une étape) :

1. **Proposition** : l'étape produit une liste large de candidats (rappel élevé), comme aujourd'hui.
2. **Juges indépendants** : au moins 3 juges, chacun avec une perspective et un prompt distincts, notent tous les candidats sur la même grille (SPEC-53f3), à l'aveugle (ils ne voient pas les autres notes), candidats anonymisés et présentés dans un ordre mélangé propre à chaque juge (biais de position). Perspectives par défaut :
   - **rétention** : accroche des 3 premières secondes, temps de visionnage, envie de revoir ;
   - **spectateur cible** : « je m'arrête ou je scrolle ? » ;
   - **monteur** : compréhensible seul, chute, coupe en frontière de phrase ;
   - **avocat du diable** : cherche les défauts (contexte manquant, ennuyeux, promesse non tenue) ;
   - **conformité** : risques (diffamation, mineur identifiable, violence gratuite, droits) ; peut poser un **veto** motivé.
   Les modèles peuvent différer d'un juge à l'autre (diversité), réglables par juge.
3. **Débat ciblé** : seuls les candidats où les juges divergent (écart au-delà d'un seuil configuré) passent un second tour où chaque juge lit les arguments anonymisés des autres et peut réviser sa note en le justifiant.
4. **Agrégation robuste et déterministe** : médiane par critère, puis score de la grille + bonus mesurés (heatmap, audio, vision), seuil min_score, non-chevauchement ; un veto conformité rejette le candidat.
5. **Traçabilité** : notes de chaque juge par tour, arguments, révisions, veto et dissidences sont écrits dans le JSON de l'étape.
6. **Calibration** : quand des décisions humaines existent (journal feedback, mode review), l'accord jury/humain est mesuré et publié ; les décisions humaines servent d'exemples aux juges.

## Contrainte (résumé)
Voir `constraint`.

## Conséquences
- Plus d'appels LLM par vidéo (juges x tours), mais chaque juge note tous les candidats en un appel et les juges tournent en parallèle : quelques appels, pas des dizaines.
- Résultat reproductible à composition de jury égale, et explicable (trace).
- Le mode review reste pour calibrer ou reprendre la main.
- Première application : sélection des moments. Même mécanisme ensuite pour les coupes (parts), l'accroche (captions) et le verdict qa.
