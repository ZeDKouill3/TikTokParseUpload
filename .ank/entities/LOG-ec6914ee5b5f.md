---
id: LOG-ec6914ee5b5f
type: log
title: "Vert: 20 tests + 1 optionnel (CLIPPER_CLAUDE_INTEGRATION=1, vrai Claude, saute par defaut)."
created: 2026-09-25T13:37:11Z
author: w-6881
scope:
  - clipper/moments.py
  - rubric.toml
  - tests/test_moments.py
about: TASK-68811e08394e
seq: 3
schema: 4
version: 1
---

 Mutations verifiees: exclusion sponsor, chevauchement, min_score, recalage, ponderation -> chaque mutation casse au moins un test. Schema LLM: notes entieres 0-10 par critere seulement (pas de score final demande), hook_text en premier; tour de comparaison final si transcription > max_transcript_chars (ids tous exiges). vision.json attendu: frames[{timecode, description, striking}] - a respecter par TASK-7632. Pipeline (TASK-66a3) doit passer examples=feedback.examples(k) a moments.run.
