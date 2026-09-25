---
id: LOG-b9419dec17fa
type: log
title: "Clauses: C1 images debut/milieu/fin + une par changement de plan (detectes dans le mp4 rendu par"
created: 2026-09-25T14:21:07Z
author: w-e116
scope:
  - clipper/qa.py
  - tests/test_qa.py
about: TASK-e116dad45d8f
seq: 2
schema: 4
version: 1
---

 histogrammes cv2, pas via reframe) envoyees en fichiers jpg a llm usage qa ; C2 transcription du clip (champ transcript du JSON) dans le prompt ; C3 schema des defauts = enum face_cut/subtitle_on_face/starts_mid_sentence/weak_hook/black_screen ; C4 qa.status passed|rejected + issues ecrits dans output/<vid>/<clip>.json ; C5 'pret' n'existe pas dans render : j'ajoute un champ ready (true seulement si qa passed) + is_ready(), rejete => ready false ; C6 local : duree reelle vs duration JSON, resolution 1080x1920, silence initial > 1 s (pcm via ffmpeg + RMS numpy) => issue source=local, rejected meme si LLM ok. Erreur LLM : remonte, JSON inchange (ADR-ad2e). Images cachees sous workspace/<vid>/qa/<clip>/.
