---
id: TASK-b41fd515af38
type: task
slug: reframe-fusionner-les-d-tections-en-double-et-ne
title: "reframe : fusionner les détections en double et ne protéger que les visages retenus"
created: 2026-09-25T19:31:56Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
blocked_by: []
done_criteria: |
  Constat essai réel 2026-09-25 (sZi-qJ-5ptA clip 00) : la détection plein cadre + tuiles produit plusieurs pistes pour la même personne (boîtes quasi identiques, ids 0/1/2), donc la règle 'ne couper aucun autre visage' se contredit : split avec deux fois le plan entier, et fallback_blur sur presque tout le clip. reframe fusionne les détections qui se recouvrent (IoU au-dessus d'un seuil de CONFIG_DEFAULTS) au sein d'une image et les pistes qui se suivent spatialement dans le temps ; seuls les visages retenus (présents au moins une part minimale de la durée du plan et d'une taille minimale, réglages documentés) doivent rester entiers ; un split n'est proposé qu'avec deux visages distincts retenus et chaque panneau cadre son visage ; la règle 'visage retenu jamais coupé' (SPEC-350f) reste vraie ; tests sur boîtes synthétiques reproduisant le cas (détections dupliquées, piste fantôme de 0,4 s) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: diagnose
schema: 4
version: 1
---
