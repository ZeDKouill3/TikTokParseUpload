---
id: LOG-bbb1f7670e8d
type: log
title: "clauses A-E vertes : fix_chunk_words=3000, fix_parallel=4 par defaut, correction en"
created: 2026-09-25T17:21:23Z
author: w-a6d4
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
about: TASK-a6d4bcbd43af
seq: 3
schema: 4
version: 1
---

 ThreadPoolExecutor(max_workers=fix_parallel), resultat identique quel que soit l'ordre (mapping par contenu de la tranche, pas par ordre d'arrivee), echec d'une tranche remonte sans ecrire. Reste F/G : transcript_raw.json + reprise sans refaire whisper.
