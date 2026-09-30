---
id: LOG-efb54f0e17da
type: log
title: "REPRODUIRE: appel isole reel jury_spectateur (candidat synthetique, prompt exact de"
created: 2026-09-30T07:32:47Z
author: w-f89fef1f74f1
scope:
  - clipper/jury.py
  - clipper/llm
  - tests/test_jury.py
  - tests/test_llm_claude_cli.py
  - tests/test_llm.py
about: TASK-f89fef1f74f1
seq: 2
schema: 4
version: 1
---

 jury._round1_prompt) -> OK, pas de 400 (script scratchpad/repro_400.py). MINIMISER/HYPOTHESE: 2 meneurs de vague 1 (retention/opus + spectateur/sonnet, jury._waves) lances en parallele via ThreadPoolExecutor comme le vrai tour 1 -> 400 'max 4 blocks, found 5' reproduit 2 fois sur 3 essais, mais sur retention (opus) les 2 fois, jamais sur spectateur (sonnet) dans mon echantillon -- donc pas specifique au role spectateur ni au modele : course intermittente entre processus 'claude -p' concurrents (l'un des 2 meneurs, variable). Un appel isole (sans concurrence) ne le reproduit jamais chez moi. INSTRUMENT confirme: nos propres blocs cache_control restent toujours a 1 (deja garanti par le code + tests existants) ; les blocs en trop viennent du cote CLI, hors controle. DECISION (criterion du createur, explicite) : reclasser ce 400 en LLMError permanent (pas TransientLLMError) malgre l'intermittence mesuree, car un rejeu n'est pas garanti et ADR-ad2e prefere un echec explicite a une file d'attente qui retente a l'aveugle. Code modifie : clipper/llm/claude_cli.py (_TRANSIENT_TEXT n'inclut plus le motif cache_control, docstring module a jour).
