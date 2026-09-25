---
id: TASK-cdc453cd2655
type: task
slug: tape-captions-titre-l-gende-hashtags-texte-d-acc
title: "Étape captions : titre, légende, hashtags, texte d'accroche"
created: 2026-09-25T09:39:45Z
author: claude-plan
status: open
scope:
  - clipper/captions.py
  - tests/test_captions.py
blocked_by: [TASK-326c092efbbb, TASK-e4925237bef2]
done_criteria: |
  Pour chaque clip, l'étape demande à clipper.llm (usage captions) titre, légende, hashtags et texte d'accroche (8 mots max) dans la langue de la vidéo, valide la réponse (longueurs, hashtags commençant par #, sans doublon) et écrit ces champs dans le JSON du clip conforme à SPEC-350f8956d7c7 ; si Claude échoue, aucune légende par défaut n'est inventée (testé, ADR-ad2e562b1810).
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Le texte d'accroche doit exister avant le rendu : captions passe avant render.
