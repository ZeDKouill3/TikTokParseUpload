---
id: LOG-536a9ddd9b52
type: log
title: "clauses : C1 .ass 1080x1920 depuis intervalle+transcription mot/mot ; C2 groupes 2-4 mots ; C3"
created: 2026-09-25T13:31:00Z
author: w-cba8
scope:
  - clipper/subtitles.py
  - clipper/assets/fonts/**
  - tests/test_subtitles.py
about: TASK-cba88d716fc6
seq: 4
schema: 4
version: 1
---

 karaoke mot courant surligne ; C4 gros texte + contour (style) ; C5 emphase via clipper.llm usage=emphasis, couleur distincte ; C6 timecodes relatifs au debut du clip ; C7 position verticale parametrable evitant une zone donnee ; C8 teste par parsing du .ass (evenements/timings/style) ; C9 rendu ffmpeg echantillon en test optionnel marque. Contraintes : CONFIG_DEFAULTS dans le module, appel LLM uniquement via clipper.llm (FakeBackend en test), pas de reseau par defaut, cache par resultat existant (ADR-b16b) sauf force.
