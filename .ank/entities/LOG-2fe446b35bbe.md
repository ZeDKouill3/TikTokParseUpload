---
id: LOG-2fe446b35bbe
type: log
title: "8 clauses (I1-I4, M1-M4) : rouge verifie par git stash du code (code original, tests nouveaux) puis"
created: 2026-10-03T15:31:57Z
author: w-2499eed470d1
scope:
  - clipper/transcribe.py
  - clipper/pipeline.py
  - clipper/worker.py
  - clipper/llm/__init__.py
  - clipper/llm/claude_cli.py
  - tests/test_transcribe.py
  - tests/test_pipeline.py
  - tests/test_worker.py
  - tests/test_llm.py
about: TASK-2499eed470d1
seq: 2
schema: 4
version: 1
---

 vert apres reapplication. 2 surprises en ecrivant les tests : (1) le fix I1 (purge fix_chunks/ au depassement du ratio de refus) rend la relance REUSSIE si le backend repond bien cette fois (pas une 2e TranscribeError comme le script de preuve de la revue le montrait sur l'ancien code) ; (2) le test I3 doit distinguer '1re fois en revue sans decision' (awaiting non vide) de 'deja revue, reprise sur un echec plus tardif' (captions deja done + decisions compl\u00e8tes) : un through_review=False naif casse ce 2e cas (une video deja decidee repasserait en awaiting_review a chaque reprise). I4 : reset attempts=0 a 2 endroits distincts (manual=True dans _start, hors process_queue ; et apres chaque etape reussie non skip dans _advance_steps), verifie independamment.
