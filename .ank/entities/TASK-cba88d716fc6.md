---
id: TASK-cba88d716fc6
type: task
slug: tape-subtitles-sous-titres-style-capcut-en-ass-m
title: "Étape subtitles : sous-titres style CapCut en .ass, mots mis en valeur"
created: 2026-09-25T09:39:43Z
author: claude-plan
status: done
scope:
  - clipper/subtitles.py
  - clipper/assets/fonts/**
  - tests/test_subtitles.py
blocked_by: [TASK-0caecdbe981e, TASK-e4925237bef2]
done_criteria: |
  Pour un intervalle [start, end] et la transcription mot par mot, l'étape génère un .ass 1080x1920 : groupes de 2 à 4 mots, mot courant surligné (karaoké), gros texte avec contour, mots d'emphase choisis par clipper.llm (usage emphasis) dans une couleur distincte ; timecodes relatifs au début du clip ; position verticale paramétrable pour éviter une zone donnée (visages) ; testé en parsant le .ass produit (nombre d'événements, timings, style) ; un rendu ffmpeg d'échantillon est produit par un test marqué optionnel.
criteria_by: creator
verify: [tests]
method: tdd
proof:
  - type: test
    ref: local/bdd97b5e0d3a@64437e9
    tree: scope/fe454f049c01
    criteria: d6c57ba96034
    verifier: tests@904a5eea5add
    via: verifier
schema: 4
version: 5
---

Police libre embarquée (ex. Montserrat ou Poppins ExtraBold, licence OFL).
