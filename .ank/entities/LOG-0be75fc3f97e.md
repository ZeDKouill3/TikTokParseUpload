---
id: LOG-0be75fc3f97e
type: log
title: "Clauses: C1 extraction audio ffmpeg 16k mono ; C2 transcript.json (language, segments start/end,"
created: 2026-09-25T11:36:37Z
author: w-0cae
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
about: TASK-0caecdbe981e
seq: 3
schema: 4
version: 1
---

 words word/start/end/probability) ; C3 modele depuis [transcribe].model, device/compute_type depuis clipper.gpu ; C4 modele libere en fin d'etape (weakref, y compris sur echec) ; C5 usage vocab depuis titre+description -> initial_prompt + hotwords ; C6 usage transcript_fix : corrections {i, word} par index, texte seul, timecodes et nombre inchanges, index hors plage = echec ; C7 par tranches ; C8 ADR-ad2e : echec LLM propage, pas de transcript ecrit, desactivation seulement explicite (vocab=false / transcript_fix=false) ; C9 cache transcript.json sauf force ; C10 integration tiny sautee par defaut (CLIPPER_WHISPER_INTEGRATION=1). Lecture : entree = workspace/<id>/<id>.mp4 + meta.json (sortie de download).
