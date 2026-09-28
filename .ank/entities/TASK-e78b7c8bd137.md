---
id: TASK-e78b7c8bd137
type: task
slug: reframe-format-letterbox-image-horizontale-zoom
title: "reframe : format letterbox (image horizontale zoomée sur fond flou), sans appel LLM"
created: 2026-09-28T17:26:11Z
author: nicoc@zedk_ordi
status: open
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
blocked_by: [TASK-05b44079fae5]
done_criteria: |
  SPEC-6127 : CONFIG_DEFAULTS de reframe gagne format = letterbox | crop (letterbox par défaut ; crop = comportement actuel inchangé) et letterbox_zoom (1,25). En letterbox, pour chaque plan : détection et suivi des visages comme aujourd'hui (visages retenus), mais aucun appel LLM layout ; layout = letterbox ; deux panneaux : background (effect blur, source entière vers 1080x1920) puis main (fenêtre source de largeur round(source_w / zoom), pleine hauteur, placée vers dest pleine largeur 1080, hauteur au prorata, centrée verticalement, dimensions paires) ; la fenêtre est centrée horizontalement, décalée au plus près du centre si un visage retenu serait coupé (entier dedans ou entier dehors), et si aucune position ne convient à un instant, zoom 1 pour tout le plan avec la raison dans reason ; plan de recadrage au même format JSON qu'aujourd'hui (render le lit sans changement) ; un zoom < 1 ou un format inconnu = ReframeError explicite. Tests sur boîtes synthétiques : aucun visage -> fenêtre centrée ; visage retenu au bord -> fenêtre décalée ; deux visages retenus aux deux bords -> zoom 1 avec raison ; aucun appel LLM (FakeBackend sans réponse) ; format crop inchangé ; toute la suite pytest reste verte.
criteria_by: creator
verify: [tests]
method: tdd
schema: 4
version: 1
---
