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
blocked_by: []
done_criteria: |
  L'étape vision : (1) n'envoie au LLM que les images autour des moments retenus et des rejetés qu'un bonus visuel pourrait faire passer (rejetés pour score sous min_score dont le score + le bonus visual de rubric.toml, dans la limite de max_total, atteint min_score) ; les autres rejetés ne sont pas décrits ; (2) envoie des images réduites à max_width pixels de large (nouveau réglage, défaut 768, proportions conservées) créées dans un dossier temporaire du workspace supprimé après l'étape, originaux intacts ; (3) traite jusqu'à parallel lots en même temps (nouveau réglage, défaut 4), chaque lot restant un appel clipper.llm validé contre son schéma, avec un vision.json identique à un traitement séquentiel (mêmes descriptions aux mêmes timecodes, ordre par timecode) ; (4) enregistre chaque lot réussi au fil de l'eau (workspace/<video_id>/vision_partial.json, écriture atomique et protégée par un verrou) et une relance après échec ne redemande pas les lots déjà décrits ; vision_partial.json est supprimé quand vision.json est écrit ; un lot en échec fait échouer l'étape avec sa raison (ADR-ad2e) ; tests sans réseau avec FakeBackend (sélection des candidats, dimensions des images reçues, nombre d'appels, reprise) ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 2
---

Essai réel 2026-09-25 : 448 images 1920x1080 (~220 Ko) envoyées pour 9 retenus + 23 rejetés, dont beaucoup ne pouvaient pas remonter. La lecture exacte du score, du min_score et du bonus visuel se fait dans moments.json et rubric.toml (sans importer clipper.moments, ADR-b16b).
