---
id: SPEC-73d05edb4a74
type: spec
slug: jury-confiance-de-chaque-juge-par-moment-prise-e
title: "Jury : confiance de chaque juge par moment, prise en compte dans le débat et l'agrégation"
created: 2026-10-01T13:18:13Z
author: nicoc@zedk_ordi
status: proposed
scope:
  - clipper/jury.py
  - clipper/moments.py
  - clipper/web/app.py
  - clipper/web/static/**
references: [ADR-ff871c8eeac5, ADR-1cf0b17d48b3, ADR-ad2e562b1810, ADR-b1c17749b528]
schema: 4
version: 1
---

## Objet
Un juge qui hésite et un juge sûr de lui pèsent aujourd'hui autant. Chaque juge donne désormais sa confiance pour chaque candidat ; elle déclenche le débat sur les cas douteux et pondère l'agrégation, sans écraser aucun juge (ADR-1cf0).

## Règles
R1. Réponse des juges. Au tour 1 et au tour 2, chaque juge renvoie pour chaque candidat un champ confidence, entier de 0 à 100 (0 = au hasard, 100 = certain), exigé par le schéma JSON envoyé au LLM (ADR-b1c1). Absent ou hors bornes = réponse de juge invalide, traitée comme les autres champs invalides (ADR-ad2e).
R2. Débat. En plus de l'écart de scores actuel, un candidat passe au débat quand au moins un juge a une confiance < [jury] debate_confidence_below (CONFIG_DEFAULTS de jury, défaut 40).
R3. Agrégation. La médiane par critère devient une médiane pondérée par (poids de calibration existant) × max(confidence/100, [jury] min_confidence_weight) (défaut 0,2 : aucun juge n'est jamais réduit à zéro). Déterministe. Test de non-régression : quand tous les juges ont la même confiance, les scores sont identiques à l'agrégation actuelle.
R4. Journal et affichage. moments.json (et le JSON du jury) garde la confiance de chaque juge par tour et la confiance agrégée du candidat (médiane des confiances finales). La console l'affiche : écran Revue (par moment) et fiche d'un clip.
R5. Aucun changement de mode : la confiance ne fait pas basculer une vidéo de auto en review ; elle n'agit que par R2 et R3.
R6. Tests sans vrai Claude (FakeBackend) : schéma exigeant confidence, réponse sans confidence refusée, déclenchement du débat par confiance basse, médiane pondérée (cas chiffrés), non-régression R3, journal R4.
