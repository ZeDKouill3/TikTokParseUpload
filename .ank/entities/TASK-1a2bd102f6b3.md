---
id: TASK-1a2bd102f6b3
type: task
slug: vision-moins-d-images-candidats-rattrapables-seu
title: "vision : moins d'images (candidats rattrapables seulement) et images réduites"
created: 2026-09-25T18:04:58Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/vision.py
  - tests/test_vision.py
blocked_by: [TASK-e9cfe6e54ec6]
done_criteria: |
  vision n'envoie au LLM que les images autour des moments retenus et des rejetés qu'un bonus visuel pourrait faire passer : rejetés pour score sous min_score dont le score + le bonus visual de rubric.toml (dans la limite de max_total) atteint min_score ; les autres rejetés (chevauchement, SponsorBlock, durée, ou score trop bas) ne sont pas décrits ; les images envoyées sont réduites à max_width pixels de large (nouveau réglage, défaut 768, proportions conservées) dans un dossier temporaire du workspace supprimé après l'étape, les originaux intacts ; tests sans réseau avec FakeBackend (sélection des candidats, dimensions des images reçues) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---

Essai réel 2026-09-25 : 448 images 1920x1080 (~220 Ko) envoyées pour 9 retenus + 23 rejetés, dont beaucoup ne pouvaient pas remonter. La lecture exacte du score, du min_score et du bonus visuel se fait dans moments.json et rubric.toml (sans importer clipper.moments, ADR-b16b).
