---
id: LOG-3233fedbfec7
type: log
title: "Clause 1 (images stream-json) : claude_cli.py construit desormais la commande sans outil Read ni"
created: 2026-09-29T21:11:32Z
author: w-b0faec889d31
scope:
  - clipper/llm
  - clipper/jury.py
  - clipper/transcribe.py
  - tests/test_llm.py
  - tests/test_llm_claude_cli.py
  - tests/test_jury.py
  - tests/test_transcribe.py
about: TASK-b0faec889d31
seq: 2
schema: 4
version: 1
---

 --add-dir ; --input-format stream-json + --output-format stream-json + --verbose (requis par le CLI reel, sinon erreur explicite) quand des images sont donnees, blocs image base64 + bloc texte dans un seul message NDJSON sur stdin. parse_output lit soit un objet JSON unique (sans image), soit le dernier evenement type=result du flux NDJSON (avec images). Mesure reelle de controle (1 image, claude 2.1.281) : input_tokens=2, cache_read_tokens=0, output_tokens=67, cout 0,0097 USD, 1 seul tour -- a comparer aux ~90k tokens de cache par appel vision (8,21 USD) mesures avec l'ancienne approche Read+add-dir (ivl0nxa3C7o).
