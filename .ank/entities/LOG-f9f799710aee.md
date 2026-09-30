---
id: LOG-f9f799710aee
type: log
title: "Entree du test de fumee reflete un vrai cas du pipeline (pas une entree irrealiste) :"
created: 2026-09-30T08:18:35Z
author: w-0d30201398b8
scope:
  - clipper/reframe.py
  - tests/test_reframe.py
  - tests/integration/test_smoke_real.py
about: TASK-0d30201398b8
seq: 4
schema: 4
version: 1
---

 clipper/reframe.py boucle 'for plan in plans: ... llm.ask(layout, ...)' (reframe(), format != letterbox) appelle layout pour CHAQUE plan detecte par le scene-detect, y compris ceux ou plan.tracks est vide (aucun visage mediapipe sur tout le plan) -- ex. un plan pur gameplay sans facecam ni visage a l'image. Le test de fumee _smoke_layout (tracks=[]) construit donc une entree que le vrai pipeline produit reellement, pas un artefact de test.
