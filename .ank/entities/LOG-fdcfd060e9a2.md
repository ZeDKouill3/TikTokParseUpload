---
id: LOG-fdcfd060e9a2
type: log
title: "ank done (2e run, apres fix concurrence) : echec inattendu sur"
created: 2026-09-30T20:06:46Z
author: w-42a46cb23f78
scope:
  - pyproject.toml
  - tests/conftest.py
  - tests/test_qa.py
  - tests/test_vision.py
  - tests/test_transcribe.py
about: TASK-42a46cb23f78
seq: 11
schema: 4
version: 1
---

 tests/test_transcribe.py::test_fix_runs_in_chunks_with_global_word_indexes_mapped_per_chunk (pas un ConcurrencyTracker). Non reproduit en isolant ce test sous 8 passages avec charge CPU synthetique (16 process de spin) -> pas une race de scheduling pure. Rejoue la suite complete une fois en diagnostic (hors ank done) : 0 echec mais 1168 passed + 25 skipped = 1193, soit 2 de plus que les 1191 tests collectes (1166+25 au baseline) -- indice d'un worker xdist relance apres crash/OOM sur cette machine partagee (16 Go, plusieurs sessions agent actives en meme temps) plutot qu'une erreur de logique de test. Reduit addopts de '-n auto' (12) a '-n 6' (coeurs physiques) pour laisser de la marge RAM/CPU, conformement a la consigne 'limite le nombre de process si la RAM sature'.
