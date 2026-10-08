---
id: TASK-4c2c8eaabb49
type: task
slug: agents-md-section-des-d-cisions-ratifi-es-r-g-n
title: "AGENTS.md : section des décisions ratifiées régénérée depuis ank (statuts exacts)"
created: 2026-10-08T23:34:08Z
author: nicoc@zedk_ordi
status: open
scope:
  - AGENTS.md
blocked_by: []
done_criteria: |
  research/reviews/drift-0910.md M7 : la section « Décisions ratifiées (ADR / SPEC) » d'AGENTS.md est périmée (SPEC-6a86 et SPEC-76dc dites proposées alors qu'acceptées le 30/09 ; SPEC-8257 superseded ; SPEC-53f3 superseded par SPEC-4063 ; SPEC-6a47 ; SPEC-4a9b, SPEC-b0f3, ADR-4e57, ADR-35b7, ADR-ff87, ADR-ca9a absentes). (1) La section est régénérée à partir de la CLI ank (ank find --type adr / --type spec, ank show ; jamais lecture de .ank/ à la main) : chaque ADR/SPEC au statut accepted listée avec son id court et un résumé d'une ou deux lignes fidèle à son corps ; les specs proposées listées à part avec « proposée, pas encore ank accept » (SPEC-4a9b ; SPEC-2a1e signalée comme doublon vide à ne pas ratifier) ; aucune spec superseded présentée comme en vigueur. (2) Le reste d'AGENTS.md est inchangé (setup, tests, règles ank, conventions, pièges, orchestration), y compris les lignes installeur ADR-e1da / SPEC-38f7 (garder leur contenu). (3) Tâche de documentation : pas de nouveau test requis ; preuve = suite de tests verte et, dans le message de commit, la liste des ids acceptés listés comparée à `ank find` (même ensemble). Texte en français, phrases courtes.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
