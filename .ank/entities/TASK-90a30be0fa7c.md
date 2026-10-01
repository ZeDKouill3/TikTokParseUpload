---
id: TASK-90a30be0fa7c
type: task
slug: comptes-cran-de-carnet-des-comptes-coffre-de-l-o
title: "Comptes : écran de carnet des comptes (coffre de l'OS), boutons Copier, générateur de mot de passe (SPEC-6fa4)"
created: 2026-10-01T12:19:17Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/accounts.py
  - clipper/web/app.py
  - clipper/web/static/**
  - pyproject.toml
  - tests/test_accounts.py
  - tests/test_web.py
blocked_by: []
done_criteria: |
  Toutes les règles R1 à R7 de SPEC-6fa409556e34 tenues à la lettre, prouvées par tests ciblés sans réseau ni vrai coffre (backend keyring en mémoire branché dans les tests) : (1) R1/R2 : ajout, modification, suppression d'un compte ; mot de passe écrit dans keyring (service clipper-accounts, clé = id), jamais dans state/accounts.json (test qui relit le fichier brut) ; écriture atomique ; refus explicite en français quand le backend keyring n'est pas sûr (fail/null/en clair), sans aucun repli ; suppression d'un compte = suppression de l'entrée du coffre ; (2) R3 : chaque route /api/accounts* répond 403 avec message explicite pour une adresse cliente hors bouclage et pour un en-tête Host étranger, même avec jeton valide ; (3) R4 : la liste ne contient jamais le mot de passe (has_password seulement) ; la route dédiée le renvoie ; aucun mot de passe dans les messages d'erreur ni dans les journaux (test caplog) ; pas d'en-tête CORS ; écritures refusées sans corps JSON ; (4) R5 : générateur via secrets, longueur 12-64 (défaut 20 dans CONFIG_DEFAULTS), au moins un caractère de chaque classe choisie, option symboles et option sans ambigus, refus explicite hors bornes ; (5) R6 : écran Comptes (fichier static/screens/accounts.js + entrée de navigation) : liste masquée, Copier identifiant, Copier mot de passe, Afficher (re-masqué après 30 s), Ajouter/Modifier/Supprimer avec confirmation, générateur qui remplit le formulaire ou copie ; avis visible quand la console est ouverte à distance ; test statique ; exemples neutres seulement ; (6) tests existants verts. python -m pytest -q tests/test_accounts.py tests/test_web.py vert.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Implémente SPEC-6fa409556e34 (ratifiée 2026-10-01) : module clipper/accounts.py + routes /api/accounts* + écran Comptes (section Configuration de la barre latérale). Dépendance keyring à ajouter à pyproject.toml.
