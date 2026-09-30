---
id: LOG-f0ab98ed7643
type: log
title: "Diagnostic : scenes.json lu par vision.py (fenetres des moments), reframe.py (_plans coupe"
created: 2026-09-30T17:51:46Z
author: w-22a989e81a23
scope:
  - clipper/scenes.py
  - tests/test_scenes.py
about: TASK-22a989e81a23
seq: 2
schema: 4
version: 1
---

 exactement a [start,end] du moment, erreur si aucun plan ne recouvre). moments.py regle de decoupe 1 : start/end = debut/fin d'une ligne de transcript.json -> un moment ne peut jamais deborder des plages de parole. audio.json (pics hors parole) n'est qu'un signal texte pour le LLM, jamais une borne de moment ; et audio tourne APRES scenes dans clipper.pipeline.STEPS, donc audio.json n'existe normalement pas encore quand scenes decode (le cas conditionnel du critere ne se produit qu'avec --force rejoue apres coup). Conclusion : transcript.json (segments) + marge suffit a couvrir tous les moments possibles ; transcript.json devient une entree obligatoire de scenes (comme scenes.json l'est pour reframe), erreur explicite si absent ou sans segment (ADR-ad2e). Basse def deja acquise par TASK-1f16 (analysis_width=256, analysis_max_fps=30) : rien a changer la, seule la restriction temporelle est nouvelle.
