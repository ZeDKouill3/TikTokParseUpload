---
id: LOG-92e2a7abf9da
type: log
title: "correction transcript_fix : ajout du champ old (ancien mot) au schema ; check via clipper.llm"
created: 2026-09-29T19:32:56Z
author: w-d5e32c9d1ab8
scope:
  - clipper/transcribe.py
  - tests/test_transcribe.py
about: TASK-d5e32c9d1ab8
seq: 2
schema: 4
version: 1
---

 (comme captions.py) refuse une correction dont old ne correspond pas au texte reel a cet index, journalisee dans llm_refusals.jsonl (ADR-ad2e) au lieu d'un TranscribeError silencieux. tests test_transcribe.py mis a jour + 2 nouveaux (old manquant, old incoherent+journalise). suite complete : 942 passed, 8 skipped.
