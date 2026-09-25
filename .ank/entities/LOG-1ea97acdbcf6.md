---
id: LOG-1ea97acdbcf6
type: log
title: "Repro reel (claude 2.1.281, sonnet, 8 JPEG sZi-qJ-5ptA, vision._prompt + response_schema(8)) : sans"
created: 2026-09-25T17:43:54Z
author: w-6807
scope:
  - clipper/llm/claude_cli.py
  - tests/test_llm.py
about: TASK-68071908452a
seq: 2
schema: 4
version: 1
---

 --json-schema, reponse valide cette fois (9 tours, pas de structured_output) -> defaut non deterministe, pas reproductible a la demande. Avec --json-schema <json> : code 0, cle 'structured_output' = dict valide contre le schema et egal a parse_json(result) ; 10 tours, 0.81 USD. Champ = structured_output.
