---
id: LOG-97c3c2f33d8d
type: log
title: "FakeBackend resert sa derniere reponse une fois epuise (liste vide : echec au 1er appel) -> les 9"
created: 2026-09-25T18:57:10Z
author: w-cf1c
scope:
  - clipper/llm/__init__.py
  - tests/test_llm.py
  - clipper/captions.py
  - tests/test_captions.py
  - clipper/llm/fake.py
  - tests/test_jury.py
  - tests/test_moments.py
  - tests/test_parts.py
  - tests/test_qa.py
  - tests/test_reframe.py
  - tests/test_subtitles.py
  - tests/test_transcribe.py
  - tests/test_vision.py
about: TASK-cf1c258aced8
seq: 4
schema: 4
version: 1
---

 tests d'etapes gardent leur sens sans reecriture. Jury : ScriptedJury comptait chaque appel comme un tour, une reparation passait pour le tour 2 et 'reparait' le juge invalide ; corrige (reparation = meme tour, detectee par le prompt d'origine en prefixe), assertions ajoutees : juge invalide encore en echec apres 1 reparation (sans quorum : SchemaError ; avec : ecarte, trace), juge repare accepte.
